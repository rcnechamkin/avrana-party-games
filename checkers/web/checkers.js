// Starts the page. The Party's shim is vendored unchanged and served from this game's own origin;
// everything the page does lives in app.mjs, and board.mjs holds its rules of touch.
//
// A phone's connection can blink while these three files load. A module that failed to arrive is
// fetched again after a pause, at a new address (a browser remembers a failed import), and the
// page says so meanwhile; nothing is taken as "no Party".
const status = document.getElementById('status');

async function load(path) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await import(attempt ? `${path}?retry=${attempt}` : path);
    } catch (error) {
      if (status) status.textContent = 'Trouble loading the game. Trying again…';
      await new Promise((resolve) => setTimeout(resolve, Math.min(500 * 2 ** attempt, 4000)));
    }
  }
}

const [app, board, shim] = await Promise.all([
  load('./app.mjs'), load('./board.mjs'), load('./avrana-party-bridge.js'),
]);

app.createApp({ document, window, board, connectParty: shim.connectParty })
  .start().catch((error) => console.error(error));
