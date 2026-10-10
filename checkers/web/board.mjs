// The pure side of the Checkers page: squares, which way the board faces, how a tap becomes a
// move, and the words for a board. No DOM, no network, nothing from the Party: tests/
// checkers_board_test.mjs runs it in Node.
//
// The server decides what is legal and sends the moves with the view (checkers/session.py); this
// module only chooses among them. A move is a list of square indices, [from, to] or
// [from, landing, landing, ...]; index = row * 8 + col, row 0 at the top, white starts at the bottom.

export const SIZE = 8;
export const sq = (row, col) => row * SIZE + col;
export const rc = (square) => [Math.floor(square / SIZE), square % SIZE];
export const isDark = (row, col) => (row + col) % 2 === 1;
const last = (list) => list[list.length - 1];

/** Chess-style names, white's side first: a1 is white's bottom-left, h8 black's far corner. */
export function squareName(square) {
  const [row, col] = rc(square);
  return 'abcdefgh'[col] + String(SIZE - row);
}

/** The squares in the order they are drawn, top-left first. Black sees the board turned round, so
 * that their own pieces are at the bottom. */
export function order(flip) {
  const squares = Array.from({ length: SIZE * SIZE }, (_, i) => i);
  return flip ? squares.reverse() : squares;
}

export const sideOf = (piece) => (piece ? piece.toLowerCase() : null);
export const isKing = (piece) => Boolean(piece) && piece === piece.toUpperCase();
export const other = (side) => (side === 'w' ? 'b' : 'w');
export const word = (side) => (side === 'w' ? 'White' : 'Black');

export function countPieces(board, side) {
  return board.filter((piece) => sideOf(piece) === side).length;
}

/** A jump's first hop spans two rows; a step spans one. */
export function isJump(move) {
  return Math.abs(rc(move[1])[0] - rc(move[0])[0]) === 2;
}

// ---- choosing a move among the legal ones ---------------------------------------------------

/** The squares a player may pick up: where some legal move starts. */
export function sources(moves) {
  return new Set(moves.map((move) => move[0]));
}

/** What a held piece may do next. `trail` is the squares chosen so far, starting with the piece.
 * Usually every legal move of the piece ends on its own square, and then the targets are those end
 * squares ("final": tap where the piece goes, however many jumps it takes). When two complete
 * captures end on the same square (a king that can go round a diamond either way) the player is
 * asked hop by hop instead ("hop"): the targets are the next landings. */
export function choices(moves, trail) {
  const cands = moves.filter((move) => trail.every((s, i) => move[i] === s) && move.length > trail.length);
  const ends = cands.map(last);
  const mode = new Set(ends).size === ends.length ? 'final' : 'hop';
  const targets = new Map();
  for (const move of cands) {
    if (mode === 'final') targets.set(last(move), isJump(move) ? 'jump' : 'move');
    else targets.set(move[trail.length], 'hop');
  }
  return { cands, targets, mode };
}

/** One tap on `square`: the new trail and, when the tap completed a legal move, that move. */
export function tap(moves, trail, square) {
  if (!moves.length) return { trail: [], move: null };
  if (!trail.length) {
    return { trail: sources(moves).has(square) ? [square] : [], move: null };
  }
  const { cands, targets, mode } = choices(moves, trail);
  if (targets.has(square)) {
    if (mode === 'final') return { trail, move: cands.find((move) => last(move) === square) };
    const next = trail.concat(square);
    const left = cands.filter((move) => move[trail.length] === square);
    return { trail: next, move: left.length === 1 ? left[0] : null };
  }
  if (square === trail[0]) return { trail: [], move: null };                       // put the piece down
  if (trail.length === 1 && sources(moves).has(square)) return { trail: [square], move: null };
  return { trail, move: null };                                                      // nothing there
}

/** A trail is still worth keeping if some legal move starts with it. */
export function trailHolds(moves, trail) {
  return !trail.length || moves.some((move) => trail.every((s, i) => move[i] === s) && move.length > trail.length);
}

// ---- words ----------------------------------------------------------------------------------

/** The accessible name of a dark square. */
export function cellLabel({ square, piece, movable = false, selected = false, target = null }) {
  const parts = [squareName(square)];
  if (piece) parts.push(`${word(sideOf(piece)).toLowerCase()} ${isKing(piece) ? 'king' : 'man'}`);
  else parts.push('empty');
  if (selected) parts.push('selected');
  else if (movable) parts.push('can move');
  if (target === 'jump') parts.push('jump here');
  else if (target === 'hop') parts.push('jump through here');
  else if (target) parts.push('move here');
  return parts.join(', ');
}

/** Squares to mark for the last move: where it began and ended, and what it took. */
export function lastMarks(lastMove) {
  const marks = new Map();
  if (!lastMove) return marks;
  for (const square of lastMove.captured) marks.set(square, 'taken');
  marks.set(lastMove.path[0], 'from');
  marks.set(last(lastMove.path), 'to');
  return marks;
}

export function describeMove(lastMove, names) {
  if (!lastMove) return '';
  const who = names[lastMove.by] || word(lastMove.by);
  const from = squareName(lastMove.path[0]), to = squareName(last(lastMove.path));
  const took = lastMove.captured.length;
  return took
    ? `${who} jumped ${from} to ${to} and took ${took === 1 ? 'a piece' : `${took} pieces`}.`
    : `${who} moved ${from} to ${to}.`;
}

/** What the result says, to this viewer: {headline, detail}. A watcher is told by name. */
export function resultLines(view) {
  const result = view.result;
  if (!result) return null;
  const names = view.names;
  const me = view.seat;
  const nameOf = (side) => (side === me ? 'You' : names[side] || word(side));
  if (result.winner === null) {
    return { headline: 'Draw', detail: 'Too long without a capture or a plain piece moving.' };
  }
  const winner = result.winner, loser = other(winner);
  const headline = me ? (winner === me ? 'You won' : 'You lost') : `${names[winner] || word(winner)} won`;
  const lost = nameOf(loser);
  const have = lost === 'You' ? 'have' : 'has';
  const detail = {
    captured: `${lost === 'You' ? 'All your pieces were' : `All of ${lost}'s pieces were`} taken.`,
    blocked: `${lost} ${have} no move left.`,
    resigned: `${lost} resigned.`,
  }[result.ending] || '';
  return { headline, detail };
}

/** The turn line. `held` says what the player is in the middle of: nothing, a piece, a hop. */
export function turnLine(view, { held = 'none' } = {}) {
  if (view.result) return null;
  const names = view.names, turn = view.turn;
  if (view.seat && turn === view.seat) {
    if (held === 'piece') return 'Tap where it goes.';
    if (held === 'hop') return 'Tap the next square to jump through.';
    return view.mustCapture ? 'Your move. A capture is compulsory.' : 'Your move.';
  }
  const name = names[turn] || word(turn);
  return view.seat ? `Waiting for ${name}.` : `${name}'s move (${word(turn).toLowerCase()}).`;
}

/** The position in words, for anyone who cannot see the board: each side's pieces by square. */
export function summary(view) {
  const list = (side) => {
    const squares = view.board.map((piece, square) => ({ piece, square })).filter(({ piece }) => sideOf(piece) === side);
    const text = squares.map(({ piece, square }) => squareName(square) + (isKing(piece) ? ' king' : ''));
    return text.length ? text.join(', ') : 'none';
  };
  return `White: ${list('w')}. Black: ${list('b')}.`;
}
