import { compareDecimal } from "../../frontend/format.mjs";

// Zero EV is not an edge, even when the user's minimum is zero.
export const passesPropEdge = (ev: string, minimum: string) =>
  compareDecimal(ev, "0") > 0 && compareDecimal(ev, minimum) >= 0;
