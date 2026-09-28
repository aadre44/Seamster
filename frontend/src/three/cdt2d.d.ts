declare module 'cdt2d' {
  // Constrained Delaunay triangulation. With `exterior: false`, triangles
  // outside the loop formed by `edges` are removed.
  export default function cdt2d(
    points: [number, number][],
    edges?: [number, number][],
    options?: { delaunay?: boolean; interior?: boolean; exterior?: boolean; infinity?: boolean },
  ): [number, number, number][]
}
