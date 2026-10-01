# V19 — TCP 3-Way Handshake Short Upgrade

Implemented in the Shorts engine:

1. **Technical pronunciation**
   - TTS converts `SYN` → `Sin`, `SYN-ACK` → `Sin Ack`, `ACK` → `Ack`.
   - `TCP`, `UDP`, and `Seq` are also normalized for clearer speech.
   - Display captions retain the original technical spelling.

2. **Word-by-word captions**
   - ASS captions now show one word at a time instead of two-word pairs.
   - Existing pop/flash animation and timing alignment remain intact.
   - Protected exam terms can still remain together where needed.

3. **TCP packet-flow overlay**
   - TCP handshake scenes can use `motion_type=tcp_packet_flow`.
   - Overlay shows Client/Server, moving SYN → SYN-ACK → ACK packets, and the exact sequence-number arithmetic:
     - `SYN: Seq = x`
     - `SYN-ACK: Seq = y, Ack = x + 1`
     - `ACK: Ack = y + 1`
   - The overlay is deterministic and does not depend on the image model drawing readable text.

4. **Exam CTA**
   - Final TCP scene becomes an exam question after the teaching is complete:
     `Exam question: after the first SYN, what state does the server enter? Drop your answer below.`
   - Expected answer is intentionally not spoken or shown.
   - The final question HUD displays the question and comment prompt.

5. **TCP-specific visual contract**
   - Hook: `TCP HANDSHAKE IN 30 SECONDS`
   - Mechanism/example scenes receive deterministic packet arithmetic and TCP packet-flow motion.
   - Final question is deterministic for TCP handshake topics.

6. **Existing thumbnail/upload system preserved**
   - No changes were made to the V18 thumbnail design engine or YouTube custom-thumbnail upload verification.

## Validation

- Targeted regression suite: **118 passed**
- FFmpeg TCP overlay smoke test: **passed**
- Python compile checks: **passed**
- Full test collection in this sandbox is blocked by missing `google.oauth2` dependencies for two pre-existing YouTube-upload test modules.
