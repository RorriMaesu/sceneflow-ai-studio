# Optional synchronized audio/video package

This package is not installed by setup or normal model discovery. The original brief requires approval before large model downloads.

**Deferred by the user:** the user declined this download during the improvement build. Continue with existing models; do not install this package without a new explicit request.

The existing native ComfyUI nodes support a single-pass LTX 2.3 image-to-video graph with audio. The proposed minimal official package is 31,149,069,528 bytes (29.01 GiB):

| File / official source | Bytes | Destination |
| --- | ---: | --- |
| [ltx-2.3-22b-dev-nvfp4.safetensors](https://huggingface.co/Lightricks/LTX-2.3-nvfp4/resolve/main/ltx-2.3-22b-dev-nvfp4.safetensors) | 21,701,367,310 | Existing ComfyUI models/checkpoints |
| [gemma_3_12B_it_fp4_mixed.safetensors](https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors) | 9,447,702,218 | Existing ComfyUI models/text_encoders |

SHA-256 values from official repository metadata:

- LTX checkpoint: `9d0a66035d5eb9bd5d2b3bd5c1dd01cea1bdab4a0c6d3db6d62b12995741905f`
- Gemma encoder: `aaca463d11e6d8d2a4bdb0d6299214c15ef78a3f73e0ef8113d5a9d0219b3f6d`

The checkpoint includes video/audio VAEs, vocoder and projections. The first probe omits optional LoRAs and upscalers. It uses the exact selected still, a small native resolution, a short valid frame count, native generated audio and full media validation. Ordinary production retains the still-first policy.

The 16 GB GPU fit is unproven. Existing offloading/DynamicVRAM and a small probe are required; installed nodes and downloaded weights alone are not successful generation evidence. No custom nodes, package upgrades, driver changes or existing model replacements are part of this plan. Interrupted downloads retain `.part` files, and exact size/hash checks precede final naming.

Sources: [official LTX NVFP4 model](https://huggingface.co/Lightricks/LTX-2.3-nvfp4), [official ComfyUI LTX 2.3 guide](https://github.com/Comfy-Org/docs/blob/main/tutorials/video/ltx/ltx-2-3.mdx). Review the model's linked license before use or redistribution. Model weights remain excluded from Git.
