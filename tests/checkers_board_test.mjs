// The pure side of the Checkers page (AVR-238): how a tap becomes a move, and the words.
//   node --test tests/checkers_board_test.mjs
// tests/test_checkers_web.py runs this too, so the Python suite covers it.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cellLabel, choices, countPieces, describeMove, isJump, lastMarks, order, resultLines, sq, squareName,
  sources, summary, tap, trailHolds, turnLine,
} from "../checkers/web/board.mjs";

const names = { w: "Ana", b: "Ben" };

test("squares have chess names, white's side first", () => {
  assert.equal(squareName(sq(7, 0)), "a1");
  assert.equal(squareName(sq(0, 7)), "h8");
  assert.equal(squareName(sq(5, 2)), "c3");
  assert.equal(squareName(sq(0, 1)), "b8");
});

test("black sees the board turned round", () => {
  assert.deepEqual(order(false).slice(0, 3), [0, 1, 2]);
  assert.deepEqual(order(true).slice(0, 3), [63, 62, 61]);
  assert.equal(new Set(order(true)).size, 64);
});

const step = [[sq(5, 2), sq(4, 1)], [sq(5, 2), sq(4, 3)], [sq(5, 4), sq(4, 3)]];

test("a tap picks up a piece that can move, then a target completes the move", () => {
  assert.deepEqual([...sources(step)].sort((a, b) => a - b), [sq(5, 2), sq(5, 4)]);
  let t = tap(step, [], sq(5, 2));
  assert.deepEqual(t, { trail: [sq(5, 2)], move: null });
  const { targets, mode } = choices(step, t.trail);
  assert.equal(mode, "final");
  assert.deepEqual([...targets.entries()], [[sq(4, 1), "move"], [sq(4, 3), "move"]]);
  t = tap(step, t.trail, sq(4, 3));
  assert.deepEqual(t.move, [sq(5, 2), sq(4, 3)]);
});

test("a tap on a square with nothing to do changes nothing", () => {
  assert.deepEqual(tap(step, [], sq(0, 1)), { trail: [], move: null });
  assert.deepEqual(tap(step, [sq(5, 2)], sq(0, 1)), { trail: [sq(5, 2)], move: null });
  assert.deepEqual(tap([], [sq(5, 2)], sq(4, 1)), { trail: [], move: null });
});

test("tapping the held piece again puts it down; tapping another piece picks that one up", () => {
  assert.deepEqual(tap(step, [sq(5, 2)], sq(5, 2)), { trail: [], move: null });
  assert.deepEqual(tap(step, [sq(5, 2)], sq(5, 4)), { trail: [sq(5, 4)], move: null });
});

test("a multi-jump is one tap on where the piece ends up", () => {
  const triple = [[sq(7, 0), sq(5, 2), sq(3, 4), sq(1, 6)]];
  const t = tap(triple, [sq(7, 0)], sq(1, 6));
  assert.deepEqual(t.move, triple[0]);
  const { targets } = choices(triple, [sq(7, 0)]);
  assert.deepEqual([...targets.entries()], [[sq(1, 6), "jump"]]);
  assert.ok(isJump(triple[0]));
  assert.equal(tap(triple, [sq(7, 0)], sq(5, 2)).move, null, "an intermediate landing is not a target here");
});

test("branches that end in different places are chosen by where they end", () => {
  const branches = [[sq(6, 3), sq(4, 1), sq(2, 3)], [sq(6, 3), sq(4, 5), sq(2, 7)]];
  assert.deepEqual(tap(branches, [sq(6, 3)], sq(2, 7)).move, branches[1]);
});

test("two complete captures that end on the same square are chosen hop by hop", () => {
  const start = sq(5, 2), a = sq(3, 4), b = sq(5, 6), c = sq(7, 4);
  const loops = [[start, a, b, c, start], [start, c, b, a, start]];
  const { targets, mode } = choices(loops, [start]);
  assert.equal(mode, "hop");
  assert.deepEqual([...targets.entries()], [[a, "hop"], [c, "hop"]]);
  // tapping the piece is not a way out when it is a place to end: only a hop moves on
  const first = tap(loops, [start], c);
  assert.deepEqual(first.move, loops[1], "one candidate left, so the move is complete");
  assert.deepEqual(tap(loops, [start], a).move, loops[0]);
});

test("a hop that still leaves two ways keeps asking", () => {
  const s = 1, x = 2, y = 3, end = 4, z = 5;
  const moves = [[s, x, y, end, s], [s, x, z, end, s]];
  const { mode, targets } = choices(moves, [s]);
  assert.equal(mode, "hop");
  assert.deepEqual([...targets.keys()], [x]);
  const first = tap(moves, [s], x);
  assert.deepEqual(first, { trail: [s, x], move: null });
  const next = choices(moves, first.trail);
  assert.deepEqual([...next.targets.keys()].sort(), [y, z]);
  assert.deepEqual(tap(moves, first.trail, z).move, moves[1]);
});

test("a held piece is kept only while some legal move still starts with the trail", () => {
  assert.ok(trailHolds(step, []));
  assert.ok(trailHolds(step, [sq(5, 2)]));
  assert.ok(!trailHolds(step, [sq(0, 1)]));
  assert.ok(!trailHolds([], [sq(5, 2)]));
});

test("every square has a name a screen reader can use", () => {
  assert.equal(cellLabel({ square: sq(5, 2), piece: "w" }), "c3, white man");
  assert.equal(cellLabel({ square: sq(5, 2), piece: "B", movable: true }), "c3, black king, can move");
  assert.equal(cellLabel({ square: sq(5, 2), piece: "w", movable: true, selected: true }), "c3, white man, selected");
  assert.equal(cellLabel({ square: sq(4, 3), piece: null, target: "move" }), "d4, empty, move here");
  assert.equal(cellLabel({ square: sq(3, 4), piece: null, target: "jump" }), "e5, empty, jump here");
  assert.equal(cellLabel({ square: sq(3, 4), piece: null, target: "hop" }), "e5, empty, jump through here");
});

test("the last move is marked where it began, where it ended and what it took", () => {
  const last = { by: "b", path: [sq(2, 1), sq(4, 3)], captured: [sq(3, 2)] };
  const marks = lastMarks(last);
  assert.equal(marks.get(sq(2, 1)), "from");
  assert.equal(marks.get(sq(4, 3)), "to");
  assert.equal(marks.get(sq(3, 2)), "taken");
  assert.equal(lastMarks(null).size, 0);
  assert.equal(describeMove(last, names), "Ben jumped b6 to d4 and took a piece.");
  assert.equal(describeMove({ by: "w", path: [sq(5, 2), sq(4, 3)], captured: [] }, names), "Ana moved c3 to d4.");
  assert.equal(describeMove({ by: "w", path: [sq(7, 0), sq(5, 2), sq(3, 4)], captured: [sq(6, 1), sq(4, 3)] }, names),
    "Ana jumped a1 to e5 and took 2 pieces.");
  assert.equal(describeMove(null, names), "");
});

const base = { names, board: Array(64).fill(null), moves: [], mustCapture: false, result: null };

test("the result is told to each viewer in their own terms", () => {
  const won = { ...base, seat: "w", result: { winner: "w", ending: "captured", plies: 9 } };
  assert.deepEqual(resultLines(won), { headline: "You won", detail: "All of Ben's pieces were taken." });
  const lost = { ...won, seat: "b" };
  assert.deepEqual(resultLines(lost), { headline: "You lost", detail: "All your pieces were taken." });
  const watching = { ...won, seat: null };
  assert.deepEqual(resultLines(watching), { headline: "Ana won", detail: "All of Ben's pieces were taken." });
  assert.equal(resultLines({ ...won, result: { winner: "w", ending: "blocked", plies: 9 } }).detail, "Ben has no move left.");
  assert.equal(resultLines({ ...lost, result: { winner: "w", ending: "blocked", plies: 9 } }).detail, "You have no move left.");
  assert.equal(resultLines({ ...won, result: { winner: "w", ending: "resigned", plies: 0 } }).detail, "Ben resigned.");
  assert.equal(resultLines({ ...lost, result: { winner: "w", ending: "resigned", plies: 0 } }).detail, "You resigned.");
  assert.equal(resultLines({ ...won, result: { winner: null, ending: "drawn", plies: 80 } }).headline, "Draw");
  assert.equal(resultLines({ ...base, seat: "w" }), null);
});

test("the turn line says whose move it is and what a capture means", () => {
  const mine = { ...base, seat: "w", turn: "w" };
  assert.equal(turnLine(mine), "Your move.");
  assert.equal(turnLine({ ...mine, mustCapture: true }), "Your move. A capture is compulsory.");
  assert.equal(turnLine(mine, { held: "piece" }), "Tap where it goes.");
  assert.equal(turnLine(mine, { held: "hop" }), "Tap the next square to jump through.");
  assert.equal(turnLine({ ...mine, turn: "b" }), "Waiting for Ben.");
  assert.equal(turnLine({ ...base, seat: null, turn: "b" }), "Ben's move (black).");
  assert.equal(turnLine({ ...mine, result: { winner: "w" } }), null);
});

test("the position can be read without the board", () => {
  const board = Array(64).fill(null);
  board[sq(5, 2)] = "w";
  board[sq(0, 1)] = "B";
  board[sq(2, 3)] = "b";
  assert.equal(summary({ board }), "White: c3. Black: b8 king, d6.");
  assert.equal(summary({ board: Array(64).fill(null) }), "White: none. Black: none.");
  assert.equal(countPieces(board, "b"), 2);
});
