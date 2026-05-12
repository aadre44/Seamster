/**
 * Sandboxed formula evaluator for parametric pattern dimensions.
 * Supports: +, -, *, /, (, ), numeric literals, and measurement variable names.
 * No eval(), no Function(), no access to globals.
 */

type Token =
  | { kind: 'num'; val: number }
  | { kind: 'id'; name: string }
  | { kind: 'op'; ch: '+' | '-' | '*' | '/' }
  | { kind: 'lparen' }
  | { kind: 'rparen' }

function tokenize(expr: string): Token[] {
  const tokens: Token[] = []
  let i = 0
  while (i < expr.length) {
    const ch = expr[i]
    if (ch === ' ' || ch === '\t') { i++; continue }
    if (ch >= '0' && ch <= '9' || ch === '.') {
      let s = ''
      while (i < expr.length && (expr[i] >= '0' && expr[i] <= '9' || expr[i] === '.')) s += expr[i++]
      tokens.push({ kind: 'num', val: parseFloat(s) })
    } else if ((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || ch === '_') {
      let s = ''
      while (i < expr.length && ((expr[i] >= 'a' && expr[i] <= 'z') || (expr[i] >= 'A' && expr[i] <= 'Z') || (expr[i] >= '0' && expr[i] <= '9') || expr[i] === '_')) s += expr[i++]
      tokens.push({ kind: 'id', name: s.toLowerCase() })
    } else if (ch === '+' || ch === '-' || ch === '*' || ch === '/') {
      tokens.push({ kind: 'op', ch: ch as '+' | '-' | '*' | '/' })
      i++
    } else if (ch === '(') { tokens.push({ kind: 'lparen' }); i++ }
    else if (ch === ')') { tokens.push({ kind: 'rparen' }); i++ }
    else throw new Error(`Unexpected character: ${ch}`)
  }
  return tokens
}

// Recursive-descent parser: expr → term (('+' | '-') term)*
// term → factor (('*' | '/') factor)*
// factor → '-' factor | '(' expr ')' | num | id

class Parser {
  private pos = 0
  constructor(
    private readonly tokens: Token[],
    private readonly vars: Record<string, number>,
  ) {}

  private peek(): Token | undefined { return this.tokens[this.pos] }
  private eat(): Token { return this.tokens[this.pos++] }

  parse(): number { return this.expr() }

  private expr(): number {
    let val = this.term()
    while (this.peek()?.kind === 'op' && (this.peek() as any).ch === '+' || this.peek()?.kind === 'op' && (this.peek() as any).ch === '-') {
      const op = (this.eat() as any).ch
      const right = this.term()
      val = op === '+' ? val + right : val - right
    }
    return val
  }

  private term(): number {
    let val = this.factor()
    while (this.peek()?.kind === 'op' && ((this.peek() as any).ch === '*' || (this.peek() as any).ch === '/')) {
      const op = (this.eat() as any).ch
      const right = this.factor()
      if (op === '/' && right === 0) throw new Error('Division by zero')
      val = op === '*' ? val * right : val / right
    }
    return val
  }

  private factor(): number {
    const t = this.peek()
    if (!t) throw new Error('Unexpected end of expression')

    // Unary minus
    if (t.kind === 'op' && t.ch === '-') {
      this.eat()
      return -this.factor()
    }
    if (t.kind === 'lparen') {
      this.eat()
      const val = this.expr()
      const closing = this.eat()
      if (closing?.kind !== 'rparen') throw new Error('Expected )')
      return val
    }
    if (t.kind === 'num') { this.eat(); return t.val }
    if (t.kind === 'id') {
      this.eat()
      const val = this.vars[t.name]
      if (val === undefined) throw new Error(`Unknown variable: ${t.name}`)
      return val
    }
    throw new Error(`Unexpected token: ${JSON.stringify(t)}`)
  }
}

export interface EvalResult {
  value: number | null
  error: string | null
}

/**
 * Evaluate a formula string against a set of measurement variables.
 * Returns { value, error } — if a variable is missing, value=null.
 */
export function evaluateFormula(formula: string, measurements: Record<string, number>): EvalResult {
  if (!formula.trim()) return { value: null, error: null }
  try {
    // Normalize measurement keys to lowercase
    const vars: Record<string, number> = {}
    for (const [k, v] of Object.entries(measurements)) vars[k.toLowerCase()] = v

    const tokens = tokenize(formula.trim())
    const parser = new Parser(tokens, vars)
    const value = parser.parse()
    if (!isFinite(value)) return { value: null, error: 'Result is not finite' }
    return { value: Math.round(value * 1000) / 1000, error: null }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    // If the error is "Unknown variable", return null value (missing measurement)
    if (msg.startsWith('Unknown variable')) return { value: null, error: msg }
    return { value: null, error: msg }
  }
}
