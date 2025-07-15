# Not guaranteed
docker run --runtime nvidia --gpus all \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    -v ~/models:/models \
    --name vllm \
    -p 8001:8000 \
    --ipc=host \
    vllm/vllm-openai:latest \
    --model /models/qwenvl/Qwen2.5-VL-32B-Instruct --quantization bitsandbytes --dtype bfloat16 --trust-remote-code --max-model-len 16384