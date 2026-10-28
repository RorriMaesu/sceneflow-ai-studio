# Optional current caption tools

Prepared 27 October 2026. These additions require a separate download choice; they are not included in the previous three-pack approval.

| Tool | Official model | Pinned revision | Model bytes |
| --- | --- | --- | ---: |
| Transcribe speech or singing | Qwen/Qwen3-ASR-0.6B-hf | 7f1569a48a89f3e3f4dc3a5c9d28bddd903bc76c | 1,576,363,223 |
| Word timing for known speech | Qwen/Qwen3-ForcedAligner-0.6B-hf | c07281df297b9905d24a508279258cccf987a064 | 1,847,225,867 |

Model total: 3,423,589,090 bytes. Each file and checksum is listed in `backend/studio/model_catalog.json`. Both model cards declare Apache 2.0. Sources: [current ASR model card](https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf), [current aligner](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf), [official release announcement](https://github.com/QwenLM/Qwen3-ASR#news).

The separate Windows/Python 3.12.12 runtime uses Transformers 5.21.0, PyTorch 2.9.0/cu128 and prebuilt wheels. It reuses verified package cache files through hardlinks, preserving the existing speech/music/effects environments and ComfyUI. Exact hashes are in `backend/runtime-locks/captions.txt`; Windows payload metadata is in `sources.json`. There are 16,907,692 bytes of additional package payloads beyond the original three runtime recipes. If the shared cache is unavailable, the conservative program-download upper bound is 3,132,996,348 bytes including setup-helper/Python allowance. Setup still reserves 12 GiB of working headroom.

Default destination is the currently selected creation-tools root on M:. Users can choose a different registered folder in Setup. Downloads remain separate from inference. A real local recording must pass transcription/alignment testing before the tool displays Ready. New versions do not replace a working production's frozen inputs.

The aligner's official languages cover speech, not verified singing alignment. Japanese and Korean word segmentation require additional dependencies; those language paths remain unavailable until separately qualified. Imported subtitles and editable script captions remain usable without these downloads. LTX remains deferred, and these caption files do not install lip-sync models.
