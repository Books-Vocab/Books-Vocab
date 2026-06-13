// Inline demo SRT for the shell-gated functional player.
//
// The web mock backend exposes the JSON editorial + progress face only; it has
// no subtitle byte route (PodcastClient has no .subtitle method — confirmed
// against web/src/api/clients.ts). To keep the functional player fully offline
// (mock-first invariant) without editing the frozen api/ layer, the player
// parses this inline SRT — timed to the 12s demo audio (src/assets/podcast_demo.mp3,
// DEMO_DURATION_SEC) so the highlighted cue actually tracks the <audio> playhead.
//
// Copy = the same first-viewport sentences the catalog fixture asserts, so the
// functional flow reads as the same episode the parity capture shows.

export const DEMO_SRT = `1
00:00:00,000 --> 00:00:02,400
Welcome back to Deep Work, Decoded.

2
00:00:02,400 --> 00:00:04,800
Today we trace the comfort crisis.

3
00:00:04,800 --> 00:00:07,200
Easy distraction quietly erodes our focus.

4
00:00:07,200 --> 00:00:09,600
The thesis is simple and a little uncomfortable.

5
00:00:09,600 --> 00:00:12,000
Discomfort chosen on purpose builds durable attention.
`
