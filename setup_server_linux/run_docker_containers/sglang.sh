# Not guaranteed
sudo docker run --gpus all \
    --shm-size 48g \
    -p 30000:30000 \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    -v ~/models:/models \
    -v ~/videos:/videos \
    --ipc=host \
    --name sglang \
    lmsysorg/sglang:latest \
    pip install vllm && python3 -m sglang.launch_server --model-path /models/qwenvl/Qwen2.5-VL-32B-Instruct-AWQ --host 0.0.0.0 --port 30000