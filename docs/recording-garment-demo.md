# Chinese Garment Demo Recording

The recording walks through the deployed solution explorer for
`demo-garment-live-20260929-v2`. This is a continuous browser recording of
previously accepted results, not a recording of a new chat or live generation.
The video labels this distinction throughout. No provider calls are made while
recording, and no model replies or progress events are inserted.

The original, verified run used DeepSeek Flash and fictitious export-order data.
The first turn retained 27 distinct feasible plans. After the UK-204 cutoff and
team B staffing update, the second turn retained 40. The saved update record
identifies `warm_restart_v1`, with 26 historical seeds in a population of 60.

The walkthrough covers the original request, objective-space selection, order
and team schedules, warehouse occupancy, the update request, updated plans,
preference selection, and JSON/CSV downloads. Original Excel inputs and the
two saved numerical iteration histories accompany the recording. The video
does not show a fresh Excel upload, model generation, or live optimization.

## Capture

`site/scripts/record_browser_session.py` starts a private Xvfb display and a
real Firefox instance. FFmpeg captures that display at 30 fps into H.264 MP4.
`record_garment_walkthrough.py` drives real browser controls and adds captions
for the recording. It never alters optimization artifacts. Saving a preference
updates only the demo's separate preference file.

The recorder refuses to reuse another display or overwrite a video. Source
assets and earlier sessions remain untouched. The paper and experiment code
are not involved.

The delivered package contains the video, original workbook and requests,
initial and updated iteration CSVs, downloaded candidates, and chapter times.
The screenshot-based legacy English marketing recording is unchanged.
