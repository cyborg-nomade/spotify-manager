# Artist Map and Album Quilt fetch reliability

Artist Map and Album Quilt share a process-local request gate. The original
batch stopped at the first provider error, so a temporary failure could leave
most of a batch unprocessed. A public MusicBrainz artist and release-group probe
reproduced transient 503 responses. Both endpoints also returned 200 in separate
public requests. The public cover example eventually completed the MusicBrainz
search and the archive redirects and returned a validated 10,703-byte JPEG.
These probes used documentation examples.

MusicBrainz and Cover Art Archive lookups can make up to six attempts for the
current artist or album. Timeouts, interrupted connections and HTTP 408, 429, 500, 502, 503 and 504
qualify. Default delays before retries are 5, 10, 20, 40 and 60 seconds,
totalling 135 seconds before the last attempt. A valid Retry-After header can
increase a wait to two minutes, with up to four minutes of scheduled retry
delays per item. An over-budget delay ends the batch and preserves the provider
cooldown for subsequent requests. Response time and work in the other view can
add to the overall elapsed time. The shared gate preserves at
least 1.1 seconds between lookups and applies provider cooldown across both
views. An album retry restarts its exact search and bounded archive reads.

A permanent error or exhausted retry stops the batch with an explanation.
Completed cache entries stay available. An ordinary Fetch skips fresh entries
and can resume with missing items after the provider recovers. Cancel interrupts
waiting immediately and drains any active blocking read. A failed attempt does
not create cached absence. Explicit absence and ambiguous results continue to
follow the existing evidence rules.

Provider retries run inside an owned lookup batch. The progress area announces
the longer wait and shows a safe reason when a lookup stops. If the browser
temporarily loses the app's local status endpoint, it checks again after five
seconds while the lookup continues.

Sources: [MusicBrainz rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)
and [Cover Art Archive response contracts](https://musicbrainz.org/doc/Cover_Art_Archive/API).

## Last.fm album covers

The quilt checks every requested album with Last.fm before using the archive
fallback. It accepts a corroborated title and complete artist credit with a
valid 174-pixel PNG or JPEG from Last.fm's image CDN. It retains the original
bytes and a link to the album catalogue. Unavailable, mismatched and
uncacheable cover results go to MusicBrainz and Cover Art Archive. A Last.fm
throttle pauses the first pass across requests. The existing Last.fm API key
stays on the server and is sent only to the API host.

The public Cher album *Believe* returned exact catalogue metadata and a
60,623-byte PNG. The two requests together took about half a second from the
local test environment. Batch times depend on how many albums require the
fallback. [Last.fm album API](https://www.last.fm/api/show/album.getInfo)

## Artist Map checkpoints and nightly refresh

**Load all missing artists** queues artists from the complete published history,
ignoring the view's date range and filters. The first pass over roughly 15,700
artists takes several hours at the MusicBrainz request rate. Each request sends
one artist name with search options. A valid unresolved result counts as a
completed lookup. A failed request stays eligible for the next run.

The Space stores complete evidence every 50 artists and flushes completed
results on a graceful stop or provider failure. A private dataset sidecar at
`derived/artist-origins-v1.jsonl.gz` uses the existing library data repository and
credential. Concurrent commits preserve the newest evidence per artist.
The map uses a local SQLite read cache restored from that checkpoint after
a rebuild. The durable archive holds up to 20,000 distinct artists.

The primary nightly library workflow checks the latest published history
after its refresh. It queues up to 250 artists without a completed lookup,
and leaves a running manual loader to finish. The next night resumes any
remaining work. Local previews use disposable storage by default. The
labelled sample preview exercises the full loader without public lookups.
The Space enables the Hub archive by default when its library backend is Hub.
`LISTENING_ORIGIN_DURABLE=false` turns off that archive.
