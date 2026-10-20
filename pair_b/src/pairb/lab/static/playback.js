// Give the player time to read the real post-move observation before the bot's reply.
export const HUMAN_MOVE_PAUSE_MS = 1000;

export async function showMoveReply(reply, display, wait = ms => new Promise(resolve => setTimeout(resolve, ms))) {
  if (reply.after_human.ply < reply.state.ply) {
    display(reply.after_human);
    await wait(HUMAN_MOVE_PAUSE_MS);
  }
  display(reply.state);
}
