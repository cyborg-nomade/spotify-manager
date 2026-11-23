# Artist Map and Album Quilt fetch reliability

Artist Map and Album Quilt share a process-local request gate. The original
batch stopped at the first provider error, so a temporary failure could leave
most of a batch unprocessed. A public MusicBrainz artist and release-group probe
reproduced transient 503 responses. Both endpoints also returned 200 in separate
public requests. The public cover example eventually completed the MusicBrainz
search and the archive redirects and returned a validated 10,703-byte JPEG.
These probes used documentation examples.

Each explicit fetch can now make up to three attempts for the current artist or
album. Timeouts, interrupted connections and HTTP 408, 429, 500, 502, 503 and 504
qualify. The waits before attempts two and three start at two and four seconds.
A valid Retry-After header can increase that wait. Longer hints than the
30-second automatic wait budget end the batch and defer subsequent requests
until the estimated cooldown is within budget. The shared gate preserves at
least 1.1 seconds between lookups and applies provider cooldown across both
views. An album retry restarts its exact search and bounded archive reads.

A permanent error or exhausted retry stops the batch with an explanation.
Completed cache entries stay available. An ordinary Fetch skips fresh entries
and can resume with missing items after the provider recovers. Cancel interrupts
waiting immediately and drains any active blocking read. A failed attempt does
not create cached absence. Explicit absence and ambiguous results continue to
follow the existing evidence rules.

Retry runs only inside an explicit fetch. There is no new background polling,
credential, cache migration or external destination. The existing progress area
announces bounded retries and distinguishes provider failure from a cache error.

Sources: [MusicBrainz rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)
and [Cover Art Archive response contracts](https://musicbrainz.org/doc/Cover_Art_Archive/API).

An alternate provider would be a separate decision if failures keep interrupting
real batches. Compare coverage with published examples and identical full-credit
matching. Spotify's artwork attribution and presentation rules would affect the
quilt and its exports. See the [Spotify album API](https://developer.spotify.com/documentation/web-api/reference/get-an-album). Country
sources need explicit evidence about what the country means and a corroborated
artist identity. Track completed batches and provider failure categories before
adding a second name lookup destination.
