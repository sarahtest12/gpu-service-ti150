# llm-infer 镜像说明：

# 1. 镜像功能描述
该镜像基于天数Base镜像版本集成了llm-modelzoo的测试代码，用于vLLM大模型的推理测试, 测试case用到的模型已经在全向箔云平台准备好，无需下载（注：如果基于该镜像做本地化部署还是需要下载模型）。
 
# 2. 镜像标签

* 镜像名称
  * mr-bi150-4.4.0-x86-ubuntu20.04-py3.10-poc-llm-infer:v1.2.3 支持vllm0.11.2
  * mr-bi150-4.4.0-aarch64-ubuntu20.04-py3.10-poc-llm-infer:v1.2.3 支持vllm0.11.2
  * mr-bi150-4.4.0-x86-ubuntu20.04-py3.10-poc-llm-infer:v1.2.4 支持vllm0.17.0
  * mr-bi150-4.4.0-aarch64-ubuntu20.04-py3.10-poc-llm-infer:v1.2.4 支持vllm0.17.0
* 默认端口：无
* 默认启动命令：无
* 依赖数据路径：
  * /share/fshare/common/models
  * /share/fshare/common/datasetes/llm-modelzoo
* 卡资源数量：参考具体case说明

<details>
  <summary>
    <b>支持的模型：</b>
  </summary>

| 模型类型 | 模型名                                 | 推理引擎     | 镜像版本   |MR/BI150         | BI100         |
|----------|---------------------------------------|-------------|-----------|-----------------|----------------|
|LLM       |glm-4-9b                               |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |glm-4-9b-chat-GPTQ-Int4                |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |glm-4-9b-chat-GPTQ-Int8                |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |GLM-4-9B-0414                          |vllm         |v1.0       |:white_check_mark:||
|LLM       |GLM-Z1-9B-0414                         |vllm         |v1.0       |:white_check_mark:||
|LLM       |glm-4-9b-0414-gptq-int4                |vllm         |v1.0       |:white_check_mark:||
|LLM       |GLM-4-32B-0414                         |vllm         |v1.0       |:white_check_mark:||
|LLM       |glm-4-32b-0414-gptq-int4               |vllm         |v1.0       |:white_check_mark:||
|LLM       |glm-4-32b-0414-gptq-int8               |vllm         |v1.0       |:white_check_mark:||
|LLM       |DeepSeek-R1-Distill-Qwen-1.5B          |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Qwen-1.5B-AWQ      |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Qwen-7B            |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Qwen-7B-AWQ        |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Qwen-14B           |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Qwen-14B-AWQ       |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Qwen-32B           |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Qwen-32B-AWQ       |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Llama-8B           |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Llama-8B-AWQ       |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Llama-70B          |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |DeepSeek-R1-Distill-Llama-70B-AWQ      |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama2-7B                              |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama2-7B-Chat-AWQ                     |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama2-13B                             |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama2-13B-Chat-AWQ                    |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama2-70B                             |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama2-70B-Chat-AWQ                    |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama-3-8B-chat                        |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Llama3-8B-Chinese-Chat                 |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Meta-Llama-3-70B                       |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen-7B                                |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen-14B                               |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen1.5-7B                             |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |CodeQwen1.5-7B                         |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen1.5-14B                            |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen1.5-32B                            |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen1.5-32B-Chat-GPTQ-Int4             |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen1.5-32B-Chat-GPTQ-Int8             |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |Qwen1.5-72B                            |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen1.5-72B-Chat-GPTQ-Int4             |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2-0.5B                             |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2-1.5B                             |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2-7B                               |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2-7B-Instruct-GPTQ-Int4            |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2-7B-Instruct-GPTQ-Int8            |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |Qwen2-57B-A14B-Instruct                |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |Qwen2-72B                              |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2-72B-Instruct-GPTQ-Int4           |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2-72B-Instruct-GPTQ-Int8           |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |Qwen2.5-0.5B-Instruct                  |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-7B-Instruct                    |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-Coder-7B-Instruct              |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-14B-Instruct                   |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-14B-Instruct-GPTQ-Int4         |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-32B-Instruct                   |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-32B-Instruct-AWQ               |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-72B-Instruct                   |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |Qwen2.5-72B-Instruct-AWQ               |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |QwQ-32B                                |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|LLM       |QwQ-32B-AWQ                            |vllm         |v1.2       |:white_check_mark:|                  |
|LLM       |Qwen3-0.6B                             |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-0.6B-GPTQ-Int8                   |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-1.7B                             |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-1.7B-GPTQ-Int8                   |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-4B                               |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-4B-AWQ                           |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-8B                               |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-8B-AWQ                           |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-14B                              |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-14B-AWQ                          |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-30B-A3B                          |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-32B                              |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-32B-AWQ                          |vllm         |v1.2       |:white_check_mark:||
|LLM       |Qwen3-235B-A22B                        |vllm         |v1.2       |:white_check_mark:||
|LLM VL    |Qwen3.5-4B                             |vllm         |v1.2       |:white_check_mark:||
|LLM VL    |Qwen3.5-9B                             |vllm         |v1.2       |:white_check_mark:||
|LLM VL    |Qwen3.5-27B                            |vllm         |v1.2       |:white_check_mark:||
|LLM       |Yi-34B                                 |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |Yi-34B-Chat-4bits                      |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |codegeex4-all-9b                       |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |codegemma-7b-it                        |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|LLM       |gemma-2b                               |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |gemma-7b                               |vllm         |v1.0       |:white_check_mark:|       :x:        |
|LLM       |Mistral-Nemo-Instruct-2407             |vllm         |v1.0       |:white_check_mark:|       :x:        |
|EMBEDDING |gte-qwen2-7b-intrust                   |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|EMBEDDING |bge-large-zh-v1.5                      |vllm         |v1.0       |:white_check_mark:|:white_check_mark:|
|EMBEDDING |jina-embeddings-v2-base-zh             |transformers |v1.0       |:white_check_mark:|:white_check_mark:|
|EMBEDDING |bce-embedding-base_v1                  |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|EMBEDDING |jina-colbert-v1-en                     |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|EMBEDDING |m3e-large                              |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|EMBEDDING |Qwen3-Embedding-0.6B                   |vllm         |v1.2       |:white_check_mark:|                  |
|RERANKER  |bge-reranker-v2-m3                     |transformers |v1.0       |:white_check_mark:|:white_check_mark:|
|RERANKER  |jina-reranker-v2-base-multilingual     |transformers |v1.0       |:white_check_mark:|:white_check_mark:|
|RERANKER  |bce-reranker-base_v1                   |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|RERANKER  |Qwen3-Reranker-0.6B                    |vllm         |v1.2       |:white_check_mark:|                  |
|IMAGE     |stable-diffusion-v1-5                  |diffusers    |v1.0       |:white_check_mark:|:white_check_mark:|
|IMAGE     |stable-diffusion-2-1-base              |diffusers    |v1.0       |:white_check_mark:|:white_check_mark:|
|IMAGE     |stable-diffusion-xl-base-1.0           |diffusers    |v1.0       |:white_check_mark:|:white_check_mark:|
|IMAGE     |stable-diffusion-3-medium-diffusers    |diffusers    |v1.0       |:white_check_mark:|:white_check_mark:|
|IMAGE     |stable-diffusion-3.5-large             |diffusers    |v1.2       |:white_check_mark:|:white_check_mark:|
|IMAGE     |FLUX.1-dev                             |diffusers    |v1.2       |:white_check_mark:|:white_check_mark:|
|IMAGE     |FLUX.1-schnell                         |diffusers    |v1.2       |:white_check_mark:|:white_check_mark:|
|AUDIO     |Belle-whisper-large-v3-zh              |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|AUDIO     |CosyVoice-300M-Instruct                |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|AUDIO     |edge-tts-zh                            |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|AUDIO     |Qwen-Audio-Chat                        |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|VL        |cogvlm2-llama3-chinese-chat-19B        |transformers |v1.2       |:white_check_mark:|       :x:        |
|VL        |internlm-xcomposer2-7b                 |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|VL        |MiniCPM-Llama3-V-2_5                   |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|VL        |MiniCPM-V-2_6                          |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|VL        |Qwen2-VL-7B-Instruct                   |transformers |v1.2       |:white_check_mark:|:white_check_mark:|
|VL        |Qwen2.5-VL-3B-Instruct                 |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|VL        |Qwen2.5-VL-7B-Instruct                 |vllm         |v1.2       |:white_check_mark:|:white_check_mark:|
|VL        |Qwen3-VL-2B-Instruct                   |vllm         |v1.2       |:white_check_mark:||
|VL        |Qwen3-VL-4B-Instruct                   |vllm         |v1.2       |:white_check_mark:||
|VL        |Qwen3-VL-8B-Instruct                   |vllm         |v1.2       |:white_check_mark:||
|VL        |llava-1.5-7b-hf                        |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |llava-1.5-13b-hf                       |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |llava-v1.6-mistral-7b-hf               |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |fuyu-8b                                |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |paligemma-3b-pt-224                    |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |chameleon-7b                           |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |MiniCPM-V-2_6                          |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |InternVL2-8B                           |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |InternVL2-26B                          |vllm         |v1.2       |:white_check_mark:|       :x:        |
|VL        |PaddleOCR-VL                           |vllm         |v1.2       |:white_check_mark:||

</details>

# 3. 镜像依赖说明：
* llm-modelzoo : http://bitbucket.iluvatar.ai:7990/projects/SWAPP/repos/llm-modelzoo/browse (master)

# 4. 镜像使用说明

## 4. 1 天数SDK的简要说明
该镜像已经预制好天数SDK开发环境 ：
* 查看GPU状态：在终端执行 ixsmi 即可查看GPU的当前状态，可以通过执行 ixsmi -h 来查看更详细的使用；
* 天数SDK安装的路径是 /usr/local/corex目录：
  * /usr/local/corex/examples 目录下有基于天数GPU卡CUDA编程的例子
  * /usr/local/corex/corex-toolbox-1.0.0/bin 目录下有常用测试工具（gemm/p2p/bandwidth/all-reduce等基本能力测试）
* 天数SDK的详细文档请从天数官网（https://www.iluvatar.com/）注册后下载。
* 天数适配的python包的安装路径是 /usr/local/corex/lib64/python3/dist-packages，该目录已经默认添加到 PYTHONPATH 中；
* 天数适配的python包可以通过执行 pip list | grep corex 查看，更新或卸载这些包会导致功能不正常，如果当前适配包的版本不能满足开发需求，请联系AE解决；

## 4.2 测试说明
该镜像提供以下几种大模型测试方法：
* 4.2.1 在线性能测试：通过部署vLLM server + 自研客户端进行测试（推荐）
* 4.2.2 基于opencompass的评测
* 4.2.3 DeepSeekV3&R1 w4a8推理
* 4.2.4 基于Open-webui + vLLM搭建可交互应用

vLLM的参数说明请参考:/root/apps/llm-modelzoo/inference/Prepare_Environment/vllm/README.md

### 4.2.1 在线推理+性能测试

* 功能说明：基于vLLM提供的openai形式server进行网络请求，计算获取以下指标: 
  * Request throughput: 每秒处理的request数
  * Output token throughput: 解码吞吐率TPS，即每秒输出的token数 
  * First Token Latency: 首字延时：平均值，中位值，p99值
  * Time per Output Token: 输出token直接的平均延时

* 测试脚本示例
    
    ```bash
    cd /root/apps/llm-modelzoo/benchmark/vllm
    
    # 启动vLLM server 服务
    python3 -m vllm.entrypoints.openai.api_server \
        --model /path/to/model --gpu-memory-utilization 0.9 \
        --max-num-batched-tokens 5120 --max-num-seqs 32 \
        --host 127.0.0.1 --port 12345

    # server端参数说明：
    ## --model 目录路径，如果是本地模型，写全路径
    ## --gpu-memory-utilization  GPU的显存使用比例，一般设置在0.9左右是默认比较保险的值，如加载模型时OOM，可适当调大一点；如果推理过程中OOM，可适当调小
    ## --max-num-batched-tokens  单个请求的最大上下文（input+output），默认值来自模型的config文件，一般比较大。可减小该参数，但一定要>=单个请求的实际大上下文（input+output）。
    ## --max-num-seqs 最大处理的batch数，主要影响prefill 和 decode 时的并发度max_num_seqs越大，能处理的请求数量就会越大，一般保持和客户端的参数num-prompts 一致即可
    ## --max_num_batched_tokens：每一次迭代中最大处理的 prefill tokens数，主要影响 prefill 的最大支持长度及并发度，这个参数一般不用设置，系统会自动计算 max_num_batched_tokens = max-model-len * max-num-seqs
    
    # 使用client端脚本，执行性能测试
    python3 benchmark_serving_tokens.py --model /path/to/model --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128 --time-interval 0
    
    # 客户端脚本参数说明：
    ## --model 保持和 server的model路径一致
    ## --num-prompt 并发请求数
    ## --input_token 输入promt的长度
    ## --output_token 输出的长度
    ## --time-interval 发送请求之间的时间间隔，默认为0

    # 数据结果说明：
    ## Request throughput: 每秒处理的request数
    ## Output token throughput: 解码吞吐率TPS，即每秒输出的token数 
    ## First Token Latency: 首字延时
    ## Time per Output Token: 输出token的平均延时

    # 如果不使用benchmark_serving_tokens.py 脚本，只是想用curl测试 vLLM server是否工作正常，可以参考以下操作：
    ## 查看server运行中模型：
       curl http://127.0.0.1:12345/v1/models
       
    ## curl发起流式请求：
        curl -s 127.0.0.1:12345/v1/completions \
            -H "Content-Type: application/json" \
            -d '{"model":"/your/model/path",
                "prompt":"Shanghai is one of the most prosperous cities in China,",
                "temperature":0.0,
                "max_tokens":128,
                "stream":"true"}'

    ## curl发起非流式请求:
        curl 127.0.0.1:12345/v1/completions \
            -H "Content-Type: application/json" \
            -d '{"model":"/your/model/path",
                "prompt":"hello. ",
                "temperature":0.0,
                "max_tokens":128}'

    ## curl发起chat请求
        curl 127.0.0.1:12345/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d '{"model":"/your/model/path",
                "messages":[{"role": "user", "content":"hello."}],
                "temperature":0.0,
                "max_tokens":128}'
    
    ## 注意：如果需要遇到某些特殊输出而终止，可以在字段中添加：
    ## "stop_token_ids":[id],(id 为 int，返回字符中将以该id对应的字符为结束字符，除非该id为特殊token id);  
    ## 或者 "stop":[id],(id 为 str，返回字符中将不带有对应的字符，并以其作为终止判断条件)。
   ```

#### LLM 模型测试样例：
* 注意：
    * server端和client端需要分别在不同的终端窗口中启动
    * 需要等待server启动完成后再启动client端

<a id="deepseekonline"></a>
<details>  
  <summary>
    <b>Deepseek系列</b>
  </summary>

```python
cd ~/apps/llm-modelzoo/benchmark/vllm

# 注：使用VLLM_ENFORCE_CUDA_GRAPH=1环境变量，和--compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'开启cuda graph
# 开启cuda graph时如遇到batch相关的错误，请根据报错调整--max-num-seqs
# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-7B/ --gpu-memory-utilization 0.9 --max-num-batched-tokens 5120 --max-model-len 2048 --max-num-seqs 32 --host 127.0.0.1 --port 12345 --trust-remote-code --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-7B/ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128   --trust-remote-code

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B/ --gpu-memory-utilization 0.9 --max-num-batched-tokens 5120 --max-model-len 2048 --max-num-seqs 32 -tp 2 --host 127.0.0.1 --port 12345 --trust-remote-code --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B/ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128   --trust-remote-code

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B/ --gpu-memory-utilization 0.9 --max-num-batched-tokens 5120 --max-model-len 2048 --max-num-seqs 32 -tp 4 --host 127.0.0.1 --port 12345 --trust-remote-code --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B/ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128   --trust-remote-code

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Llama-8B/ --gpu-memory-utilization 0.97 --max-num-batched-tokens 8192 --max-model-len 8192  --max-num-seqs 32 --host 127.0.0.1 --port 12345 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Llama-8B/ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128  

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Llama-70B/ --gpu-memory-utilization 0.9 --max-num-batched-tokens 8192 --max_model_len 8192 --max-num-seqs 32 -tp 8 --host 127.0.0.1 --port 12345 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Llama-70B/ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128  

###awq
# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B-AWQ/ --gpu-memory-utilization 0.9 --max-num-batched-tokens 5120 --max-model-len 2048 --max-num-seqs 32 -tp 1 --host 127.0.0.1 --port 12345 --trust-remote-code --quantization awq --dtype float16 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B-AWQ/ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128   

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-AWQ/ --gpu-memory-utilization 0.9 --max-num-batched-tokens 8192 --max-model-len 8192 --max-num-seqs 32 -tp 2 --host 127.0.0.1 --port 12345 --trust-remote-code --quantization awq --dtype float16 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-AWQ/ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128     
```
</details>

<a id="qwenonline"></a>
<details>  
  <summary>
    <b>Qwen系列</b>
  </summary>

```python
cd ~/apps/llm-modelzoo/benchmark/vllm

# 注：使用VLLM_ENFORCE_CUDA_GRAPH=1环境变量，和--compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'开启cuda graph
# 开启cuda graph时如遇到batch相关的错误，请根据报错调整--max-num-seqs
# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3-4B --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345  --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3-4B --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128 

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/QwQ-32B --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 4 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/QwQ-32B --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128 

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3-30B-A3B --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 2 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3-30B-A3B --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128 

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3-235B-A22B --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 16 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3-235B-A22B --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128 

# Qwen3.5系列模型要开启环境变量VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1
# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.5-4B --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3.5-4B --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 128 --output-tokens 128 

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.5-9B-AWQ --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3.5-9B-AWQ --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 128 --output-tokens 128

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.5-27B --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 4 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3.5-27B --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 128 --output-tokens 128 

# W4A8模型需要开启环境变量VLLM_W8A8_MOE_USE_W4A8=1
# W4A8模型下载地址:
# https://modelscope.cn/models/iluvatar-corex/Qwen3.5-35B-A3B-W4A8
# https://modelscope.cn/models/iluvatar-corex/Qwen3.6-35B-A3B-W4A8
# server 端
VLLM_W8A8_MOE_USE_W4A8=1 VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.5-35B-A3B-W4A8  --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3.5-35B-A3B-W4A8 --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 128 --output-tokens 128 

# server 端
VLLM_W8A8_MOE_USE_W4A8=1 VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.6-35B-A3B-W4A8  --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --max-num-seqs 32 --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/Qwen/Qwen3.6-35B-A3B-W4A8 --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 128 --output-tokens 128 

# Qwen3.5/3.6系列，可以选择开启MTP进行测试，默认使用num_speculative_tokens=1，也可在实际测试场景下根据命中率按需调整
# moe模型暂不支持同时开启CG和MTP
# 开启MTP时，用真实数据集进行测试更为准确
cd ~/apps/llm-benchmark
# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.5-9B --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice   --tool-call-parser qwen3_coder --trust-remote-code --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}' --max-num-seqs 32 --speculative-config '{"method":"qwen3_5_mtp","num_speculative_tokens": 1}'
# client 端
./iluvatar_bench perf --parallel 1 --number 1 --model /share/fshare/common/models/Qwen/Qwen3.5-9B-AWQ --url http://127.0.0.1:12345/v1/chat/completions --api openai --dataset share_gpt_zh --max-tokens 1024 --min-tokens 1024 --prefix-length 0 --min-prompt-length 1024  --max-prompt-length 1024 --tokenizer-path /share/fshare/common/models/Qwen/Qwen3.5-9B-AWQ

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.5-27B-AWQ --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice --tool-call-parser qwen3_coder --trust-remote-code --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}' --max-num-seqs 32 --speculative-config '{"method":"qwen3_5_mtp", "num_speculative_tokens": 1}'
# client 端
./iluvatar_bench perf --parallel 1 --number 1 --model /share/fshare/common/models/Qwen/Qwen3.5-27B-AWQ --url http://127.0.0.1:12345/v1/chat/completions --api openai --dataset share_gpt_zh --max-tokens 1024 --min-tokens 1024 --prefix-length 0 --min-prompt-length 1024  --max-prompt-length 1024 --tokenizer-path /share/fshare/common/models/Qwen/Qwen3.5-27B-AWQ

# server 端
VLLM_ENFORCE_CUDA_GRAPH=1 VLLM_KV_DISABLE_CROSS_GROUP_SHARE=1 python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3.6-27B-AWQ --gpu-memory-utilization 0.9 --max-model-len 2048 -tp 1 --host 127.0.0.1 --port 12345 --enable-auto-tool-choice --tool-call-parser qwen3_coder --trust-remote-code --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}' --max-num-seqs 32 --speculative-config '{"method":"qwen3_5_mtp", "num_speculative_tokens": 1}'
# client 端
./iluvatar_bench perf --parallel 1 --number 1 --model /share/fshare/common/models/Qwen/Qwen3.6-27B-AWQ --url http://127.0.0.1:12345/v1/chat/completions --api openai --dataset share_gpt_zh --max-tokens 1024 --min-tokens 1024 --prefix-length 0 --min-prompt-length 1024  --max-prompt-length 1024 --tokenizer-path /share/fshare/common/models/Qwen/Qwen3.6-27B-AWQ
```
</details>


<a id="llamaonline"></a>
<details>  
  <summary>
    <b>Llama 系列</b>
  </summary>

```python
cd ~/apps/llm-modelzoo/benchmark/vllm

# 注：使用VLLM_ENFORCE_CUDA_GRAPH=1环境变量，和--compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'开启cuda graph
# 开启cuda graph时如遇到batch相关的错误，请根据报错调整--max-num-seqs
# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/meta-llama/Llama-3-8B-chat --gpu-memory-utilization 0.9 --max-model-len 2048 --max-num-seqs 32 --host 127.0.0.1 --port 12345
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/meta-llama/Llama-3-8B-chat --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128  

# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/meta-llama/Meta-Llama-3-70B --gpu-memory-utilization 0.9 --max-model-len 2048 --max-num-seqs 32 -tp 8 --host 127.0.0.1 --port 12345
# client 端
python3 benchmark_serving_tokens.py --model /share/fshare/common/models/meta-llama/Meta-Llama-3-70B --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128 
```
</details>


<a id="chatglmonline"></a>
<details>  
  <summary>
    <b>GLM系列</b>
  </summary>

```python
cd ~/apps/llm-modelzoo/benchmark/vllm

# 注：使用VLLM_ENFORCE_CUDA_GRAPH=1环境变量，和--compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}'开启cuda graph
# 开启cuda graph时如遇到batch相关的错误，请根据报错调整--max-num-seqs
# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/THUDM/glm-4-9b-chat-1m --gpu-memory-utilization 0.9 --max-model-len 2048 --max-num-seqs 32 --host 127.0.0.1 --port 12345 --trust-remote-code
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/THUDM/glm-4-9b-chat-1m --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128

# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/THUDM/codegeex4-all-9b --gpu-memory-utilization 0.9 --max-model-len 2048 --max-num-seqs 32 --host 127.0.0.1 --port 12345 --trust-remote-code
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/THUDM/codegeex4-all-9b --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128

# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/THUDM/glm-4-9b-chat-GPTQ-Int8 --gpu-memory-utilization 0.9 --max-model-len 2048 --max-num-seqs 32 --host 127.0.0.1 --port 12345 --quantization gptq --trust-remote-code
# client 端
python3  benchmark_serving_tokens.py --model /share/fshare/common/models/THUDM/glm-4-9b-chat-GPTQ-Int8 --host 127.0.0.1 --port 12345 --num-prompts 32 --input-tokens 256 --output-tokens 128
```
</details>

#### VLM模型：
* 注意：
    * server端和client端需要分别在不同的终端窗口中启动
    * 需要等待server启动完成后再启动client端

<a id="qwenvlonline"></a>
<details>  
  <summary>
    <b>QwenVL系列</b>
  </summary>

```python
cd ~/llm-infer/vllm/vl/online

# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen2.5-VL-7B-Instruct --limit-mm-per-prompt image=5 --tensor_parallel_size 1 --gpu-memory-utilization 0.9 --host 0.0.0.0 --port 9997 --dtype bfloat16 --max-model-len 8192
# client 端
python3 benchmark_serving_vl.py --model /share/fshare/common/models/Qwen/Qwen2.5-VL-7B-Instruct --num-prompts 16 --output-tokens 512
# 一次性测试360p、720p、1080p不同分辨率图片的单词推理耗时，注意：需要把脚本里的model、host、port修改与服务一致
python3 bench_vlm.py

# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen2.5-VL-3B-Instruct --limit-mm-per-prompt image=2 --tensor-parallel-size 1 --gpu-memory-utilization 0.9 --host 0.0.0.0 --port 9997 --dtype float16 --max-model-len 65536
# client 端
python3 benchmark_serving_vl.py --model /share/fshare/common/models/Qwen/Qwen2.5-VL-3B-Instruct --num-prompts 16 --output-tokens 512

# 注意：对于Qwen3-VL模型，如果SDK 低于4.4.0，需要执行以下动作升级vLLM和torch包
#MR100/BI150
cd /share/fshare/poc/llm-infer/qwen3-vl-4.3.0
#TY1200 
cd /mnt/share/fshare/poc/llm-infer/qwen3-vl-4.3.0
pip install torch*.whl && pip install ixformer-0.6.0+corex.4.4.0.20251125-cp310-cp310-linux_x86_64.whl
pip uninstall vllm && pip install vllm-0.11.0+corex.4.3.0-py3-none-any.whl
cp /usr/local/corex/lib64/libcuinfer.so.7 /usr/local/corex/lib64/libcuinfer.so.7.bk && cp libcuinfer.so.7 /usr/local/corex/lib64/

# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3-VL-4B-Instruct --tensor_parallel_size 1 --gpu-memory-utilization 0.9 --host 0.0.0.0 --port 9997 --dtype bfloat16 --max-model-len 8192
# client 端
python3 benchmark_serving_vl.py --model /share/fshare/common/models/Qwen/Qwen3-VL-4B-Instruct --num-prompts 16 --output-tokens 512

# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3-VL-8B-Instruct-AWQ-4bit --tensor_parallel_size 1 --gpu-memory-utilization 0.9 --host 0.0.0.0 --port 9997 --dtype bfloat16 --max-model-len 8192
# client 端
python3 benchmark_serving_vl.py --model /share/fshare/common/models/Qwen/Qwen3-VL-8B-Instruct-AWQ-4bit --num-prompts 16 --output-tokens 512

# 注意，如果遇到加载完模型预留kvcache时oom，无法支持想要的上下文，可以使用参数--limit-mm-per-prompt '{"image": {"count": 1, "width": 512, "height": 512}, "video": {"count": 1, "width": 250, "height": 250, "num_frames": 5}}'，其中count根据并发需要调整，num_frames根据所需帧数调整，width、height根据可接受的最小分辨率进行调整

```
</details>


<a id="other vl"></a>
<details>  
  <summary>
    <b>其他vl模型</b>
  </summary>

```python
# PaddleOCR-VL
# 注意针对PaddleOCR-VL模型，如果SDK低于4.4.0需要先执行以下动作，升级torch、vllm包
# MR100/BI150
cd /share/fshare/poc/llm-infer/qwen3-vl-4.3.0
# TY1200 
cd /mnt/share/fshare/poc/llm-infer/qwen3-vl-4.3.0
# server 端  
pip install torch*.whl && pip install ixformer-0.6.0+corex.4.4.0.20251125-cp310-cp310-linux_x86_64.whl
pip uninstall vllm && pip install vllm-0.11.2+corex.4.3.0-py3-none-any.whl
cp /usr/local/corex/lib64/libcuinfer.so.7 /usr/local/corex/lib64/libcuinfer.so.7.bk && cp libcuinfer.so.7 /usr/local/corex/lib64/

vllm serve /share/fshare/common/models/PaddlePaddle/PaddleOCR-VL --trust-remote-code --max-num-batched-tokens 16384 --no-enable-prefix-caching --mm-processor-cache-gb 0
# client端
cd /root/llm-infer/vllm/vl/online
python3 infer_ocr.py

cd /root/llm-infer/vllm/vl
# llava-1.5-7b-hf
python3 infer.py --model /share/fshare/common/models/llava-hf/llava-1.5-7b-hf   --trust-remote-code  --model-type llava  --gpu-memory-utilization 0.95 

#llava-1.5-13b-hf
python3 infer.py --model /share/fshare/common/models/llava-hf/llava-1.5-13b-hf   --trust-remote-code  --model-type llava  --gpu-memory-utilization 0.95 

#llava-v1.6-mistral-7b-hf
python3 infer.py --model /share/fshare/common/models/llava-hf/llava-v1.6-mistral-7b-hf   --trust-remote-code  --model-type llava-next  --gpu-memory-utilization 0.95 

#fuyu-8b
python3 infer.py --model /share/fshare/common/models/adeptai/fuyu-8b   --trust-remote-code  --model-type fuyu  --gpu-memory-utilization 0.95 

#paligemma-3b-pt-224
python3 infer.py --model /share/fshare/common/models/google/paligemma-3b-pt-224   --trust-remote-code  --model-type paligemma  --gpu-memory-utilization 0.95 

#chameleon-7b
python3 infer.py --model /share/fshare/common/models/facebook/chameleon-7b   --trust-remote-code  --model-type chameleon  --gpu-memory-utilization 0.95 

#MiniCPM-V-2_6
python3 infer.py --model /share/fshare/common/models/openbmb/MiniCPM-V-2_6 --trust-remote-code  --model-type minicpmv  --gpu-memory-utilization 0.95 --max-model-len 2048

#InternVL2-8B
python3 infer.py --model /share/fshare/common/models/InternLM/InternVL2-8B --trust-remote-code  --model-type internvl_chat  --gpu-memory-utilization 0.95  --max-model-len 2048

#InternVL2-26B
python3 infer.py --model /share/fshare/common/models/InternLM/InternVL2-26B --trust-remote-code  --model-type internvl_chat  --gpu-memory-utilization 0.95  --max-model-len 2048 -tp 2
```
</details>

#### Image模型：
<details>  
  <summary>
    <b>测试样例</b>
  </summary>

```python
(注: sd系列需要的transfomers版本为4.44.2，测试时需要降版本到4.44.2)
cd /root/apps/llm-modelzoo/inference/diffusers/official

#sd1.5, 修改demo.py中StableDiffusionPipeline.from_pretrained的模型路径为:/share/fshare/common/models/stabilityai/stable-diffusion-v1-5
PT_SDPA_ENABLE_HEAD_DIM_PADDING=1 python3 demo.py
#版本sd1.5, 4.2.0 推理镜像需要使用下面的指令
ENABLE_FLASH_ATTENTION_WITH_HEAD_DIM_PADDING=1 python3 demo.py

#sd2.1, 修改demo.py中StableDiffusionPipeline.from_pretrained的模型路径为:/share/fshare/common/models/stabilityai/stable-diffusion-2-1-base
python3 demo.py
#sdxl,  修改demo_xl.py中StableDiffusionPipeline.from_pretrained的模型路径为:/share/fshare/common/models/stabilityai/stable-diffusion-xl-base-1.0
python3 demo_xl.py
#sd3, 修改demo_sb3.py中StableDiffusionPipeline.from_pretrained的模型路径为:/share/fshare/common/models/stabilityai/stablediffusion3/stable-diffusion-3-medium-diffusers。
#另外，测试此case时，需要卸载apex(pip3 uninstall apex),否则会报错
python3 demo_sb3.py

#sd3.5
cd /root/llm-infer/diffusers/sd3.5
python3 demo_sd3_5.py

#FLUX.1-dev
cd /root/llm-infer/diffusers/flux
python3 demo_flux_dev.py

#FLUX.1-schnell
cd /root/llm-infer/diffusers/flux
python3 demo_flux_schnell.py
```
</details>

#### Embedding模型:
<details>  
  <summary>
    <b>测试样例</b>
  </summary>

```python

# 在线测试
# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/BAAI/bge-large-zh-v1.5   --host 127.0.0.1 --port 12345  --trust-remote-code
# client 端

curl http://localhost:12345/v1/embeddings \
    -H "Content-Type: application/json" \
    -d '{
        "model": "/share/fshare/common/models/BAAI/bge-large-zh-v1.5",
        "input": "示例文本"
    }'

#Qwen3-Embedding-0.6B
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/Qwen/Qwen3-Embedding-0.6B   --host 127.0.0.1 --port 12345  --trust-remote-code

```
</details>

#### Reranker模型：
<details>  
  <summary>
    <b>测试样例</b>
  </summary>

```python

# 在线测试
# server 端
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/BAAI/bge-reranker-v2-m3   --host 127.0.0.1 --port 12345  --trust-remote-code
# client 端
curl http://localhost:12345/v1/rerank \
    -H "Content-Type: application/json" \
    -d '{
        "model": "/share/fshare/common/models/BAAI/bge-reranker-v2-m3",
        "query": "查询文本",
        "documents": ["文本1", "文本2"]
    }'
```
</details>

#### Audio模型：
<details>  
  <summary>
    <b>测试样例</b>
  </summary>

```python
#Belle-whisper-large-v3-zh
cd /root/llm-infer/transformers/audio/Belle-whisper-large-v3-zh
python3 infer.py

#CosyVoice-300M-Instruct
cd /root/llm-infer/transformers/audio/CosyVoice-300M-Instruct
1）目录CosyVoice是官方源码, 已从github上下载。 也可以通过git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git 下载更新版本。
2）因为使用了Matcha-TTS,所以还需要将Matcha-TTS的路径加入到PYTHONPATH中，否则会找不到Matcha-TTS的代码。命令如下:
   export PYTHONPATH=/root/llm-infer/transformers/audio/CosyVoice-300M-Instruct/CosyVoice/third_party/Matcha-TTS:${PYTHONPATH}
3）需要安装python库, pip install -r requirements.txt, 注意: requirements.txt为CosyVoice-300M-Instruct目录下的文件，不是CosyVoice目录下的requirements.txt。
4）使用方式: (1). 脚本执行: cd CosyVoice && python3 infer.py  
            (2). webui: cd CosyVoice && python3 webui.py --port 50000 --model_dir /share/fshare/common/models/CosyVoice/CosyVoice-300M-Instruct

#edge-tts-zh
cd /root/llm-infer/transformers/audio/edge-tts-zh
pip install edge-tts==6.1.18
python3 edge-tts-zh/data_process.py

#Qwen-Audio-Chat
cd /root/llm-infer/transformers/audio/Qwen-Audio-Chat
python3 infer.py
```
</details>

### 4.2.2 基于opencompass的评测
参见: [opencompass README](README_opencompass.md).

### 4.2.3 DeepSeekV3&R1 w4a8 推理支持

* 环境：单机8卡BI150

* 设置服务器performance模式
```bash
/reset/set_cpu_governor -m performance （如果是裸机容器部署忽略这句）
```

* 性能测试：
```bash
cd /root/apps/llm-modelzoo/inference/DeepSeekV3/vllm/w4a8_and_w8a8/performance
export VLLM_PP_LAYER_PARTITION="18,16,15,12"
export VLLM_W8A8_MOE_USE_W4A8=1
export VLLM_MLA_DISABLE=0
bash test_performance_server.sh --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-int4-pack8/  --tensor-parallel-size 4 --pipeline-parallel-size 4  --trust-remote-code --max-model-len 4096 --host 127.0.0.1 --port 12345 --gpu_memory_utilization 0.95 ,--model  /share/fshare/common/models/deepseek-ai/DeepSeek-R1-int4-pack8/ --host 127.0.0.1 --port 12345 --num-prompts 30 --input-tokens 1024 --output-tokens 1024
```

* 精度测试：
```bash
# 在终端中执行server
export VLLM_PP_LAYER_PARTITION="9,7,7,7,7,8,8,8"
export VLLM_W8A8_MOE_USE_W4A8=1
export VLLM_MLA_DISABLE=0
python3 -m vllm.entrypoints.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-int4-pack8/  --pipeline-parallel-size 8  --tensor-parallel-size 2 --trust-remote-code --max-model-len 8192 --gpu_memory_utilization 0.95 --port 12345
# 在另一个终端中执行
cd cd /root/apps/llm-modelzoo/inference/DeepSeekV3/vllm/w4a8_and_w8a8/mmlu
bash download_data.sh
python3 bench_other.py --backend vllm --parallel 1 --port 12345
```

* 服务部署：
```bash
# 在终端中执行server
export VLLM_PP_LAYER_PARTITION="9,7,7,7,7,8,8,8"
export VLLM_W8A8_MOE_USE_W4A8=1
export VLLM_MLA_DISABLE=0
## VLLM_ENFORCE_CUDA_GRAPH 加速推理
VLLM_ENFORCE_CUDA_GRAPH=1 python3 -m vllm.entrypoints.openai.api_server --model DeepSeek-R1-int4-pack8 --pipeline-parallel-size 8  --tensor-parallel-size 2 --trust-remote-code --max-model-len 16000  --compilation_config '{"cudagraph_mode": "FULL_DECODE_ONLY", "level": 0}' --gpu_memory_utilization 0.9 --host 0.0.0.0  --port 7860

# 在另一个终端中执行
curl http://127.0.0.1:7860/v1/chat/completions   -H "Content-Type: application/json"   -d '{ 
    "model": "DeepSeek-R1-int4-pack8",
    "messages": [
      {"role": "user", "content": "讲个1000字的故事"}
    ],
    "temperature": 0,
    "max_tokens": 12800
}'

```

### 4.2.4 基于Open-webui + vLLM搭建可交互应用

* 用vLLM启动大模型服务
参考4.2.1小节启动相关的模型服务，当终端出现 “Uvicorn running on socket ('0.0.0.0', 12345) (Press CTRL+C to quit)” 时表示启动完成，例如：
```base
python3 -m vllm.entrypoints.openai.api_server --model /share/fshare/common/models/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B/ --gpu-memory-utilization 0.9 --max-num-batched-tokens 5120 --max-model-len 2048 --max-num-seqs 32 --host 127.0.0.1 --port 12345 --trust-remote-code
```

* 拉取 open-webui镜像，启动容器，映射 8080 端口，启动open-webui服务

```base
export ENABLE_OPENAI_API=true
export ENABLE_OLLAMA_API=false
## 设置API KEY，若模型服务没有设置API key，这里可以任意设置
export OPENAI_API_KEY=123456  
## 设置模型服务的endpoint，修改llm模型服务的pod的ip，端口保持和llm服务端口一致。
export OPENAI_API_BASE_URL=http://x.x.x.x:12345/v1  


# 配置EMBEDDING模型服务（可选）
## 如使用open-webui 默认的sentence-transformers/all-MiniLM-L6-v2 模型作为embbeding服务，openwebui启动时默认会去huggingface下载，如果网络不通需要先下载到本地并拷贝到/root/ 目录下。
cp -rf /share/fshare/common/models/sentence-transformers /root/
# 启动 open-webui
open-webui serve

# 当出现 “Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)” 表示 open-webui启动成功；打开浏览器 http://zibo.saas.iluvatar.com.cn:xxxx 注：xxxx为8080的映射端口
```


# 5. 常见问题
问题1: 假设使用llama13b-16k或者更长支持长度模型,在使用单卡默认输入时,会产生以下错误: 
"The model's max seq len (16384) is larger than the maximum number of tokens that can be stored in KV cache (). Try increasing gpu_memory_utilization or decreasing max_model_len when initializing the engine." 

解释：这表明gpu显存无法支持该max_model_len参考大小, 因此需要增大 gpu_memory_utilization 或者 减少 max_model_len. 
通常,增大tp也可以解决该问题. 假设此时KV cache () 为 3481,得知此时的最大支持长度为3481,可以设置 max-model-len 3096 来解决改问题.

问题2: 设定不合理的max-num-batched-tokens, 假设使用 4K 长度模型,但是手动设置了 --max-num-batched-tokens 2048,会产生以下错误: 
" max_num_batched_tokens (2048) is smaller than max_model_len (4096). This effectively limits the maximum sequence length to max_num_batched_tokens and makes vLLM reject longer sequences. Please increase max_num_batched_tokens or decrease max_model_len. ". 

解释：该错误提升模型可处理的大小大于设定的小于,严格而言,这不是一个"错误",但会影响模型的性能。
max-num-batched-tokens 的意义如下:假设设置max-num-batched-tokens 为 32768, 这是模型可以处理的 prompt token 的总量,比如 1 * 32768, 4 * 8192等. 更通常来说,设定输入 prompt token 数为变量 x, a b 等为变量 x 的实际值, (a + b + c + .... + a1 + b1) <= 32768 的集合 (a, b, c, ..., a1, b1) 可以一次被模型处理,但前提是集合的元素数量需要小于 max-num-seqs (这是max-num-seqs 的作用之一,另一个作用是限制decode时的并发度). 因此,当该错误出现时,在显存足够的情况下,建议增加 max-num-batched-tokens 而非降低 max-model-len。

问题3：输出长度不符合预期. 

解释：在vllm中,限制模型prompt的长度低于config文件中设置的模型最大支持长度, 如果输入文本超过该长度，将不对该文本进行处理，直接返回。因此，问题需要更长的模型支持长度。
对于性能测试而言：建议在GPU 显存足够的情况下尽可能的增大 max-num-batched-tokens 和 max-model-len, 设置的方法是 (KV blocks) * 16 略大于 (输入 + 输出) * max-model-len, 即(max-num-batch-tokens + 输出 * max-model-len),这是因为 KV cache不只用于prompt,也要用于后续解码. 通常,在确认输入输出情况时(性能测试时),可以方便确认 max-model-len的设置. 但需要注意的时, 可以在此基础上适当增加max-model-len, 这和vllm的计算方法有关, 设当增加 max-model-len 可以增大并行度，但也不会应为过多的重计算减少总体性能，过大的 max-model-len 可能带来过大的重计算开销，反而减少总体性能.(这里的重计算开销指 First token 计算开销,通常文本输入长度较低时,增大max-model-len带来的性能开销不严重,有兴趣可以阅读vllm/core/scheduler.py的python源码) 在实际应用中,需要根据实际场景确认并发度和输入文本长度统计来确认这两个值。

问题4: 输出中带有<|endoftext|>,<|im_end|>,<|im_start|>的字符

解释: 这些是输出文本中的停止符，如果采样的参数中没有设置stop参数时，文本将一直输出到不超过out_tokens长度的tokens。并且带有<|endoftext|>,<|im_end|>,<|im_start|>字符。所以，如果希望输出文本为正常对话，那么需要设置stop参数，此参数的类型为:list[str]。例如: --stop ['<|endoftext|>','<|im_end|>','<|im_start|>']。

问题5: stop_token_ids参数的作用

解释: 除了问题4中的停止词外，部分模型还有自定义的停止词。比如: qwen系列，在qwen系列的generation_config.json中一般会配置“"eos_token_id": 151643”，其中151643就是qwen模型的自定义停止词的token id。所以，如果需要设置模型自定义的停止词时，可以通过stop_token_ids参数来设置。此参数的类型为: list[int].例如: --stop_token_ids [151643]。

问题6: 模型加载过慢

解释: 现在模型都是在网络共享盘/share/fshare/common/models中，各个节点服务器加载模型时，有可能出现非常慢的情况。如果遇到这类情况，可以将需要测试的模型从/share/fshare/common/models 网络共享盘 拷贝 容器中/root/apps/，然后修改 --model 模型路径参数。

问题7: inputtokens和outputtokens过大，导致无法执行推理

解释: 当inputtokens+outputtokens大于max_model_len时，会导致推理无法进行。max_model_len的来源于模型的config.json中的参数max_position_embeddings，n_positions，max_seq_len，seq_length，model_max_length，max_sequence_length，max_seq_length和seq_len所设置的最小值。
例如: llama2系列中配置文件中max_position_embeddings的值一般默认是4096，当测试inputtokens=4096，outputtokens=4096时，需要手动修改配置文件中的
max_position_embeddings。

# 6. 镜像升级历史记录：

## 1.MR-BI150
|  镜像名称    | 更新记录  |  更新日期  |
| :----------- | --------: | :--------: |
mr-bi150-4.2.0-x86-ubuntu20.04-py3.10-poc-llm-infer:v1.2 | SDK升级到4.2.0，MR/BI150版本统一 |  2025.01.24|
mr-bi150-4.2.0-x86-ubuntu20.04-py3.10-poc-llm-infer:v1.2.2 | 将vllm0.6.6的包打到镜像里 |  2025.02.18|
mr-bi150-4.2.0-x86-ubuntu20.04-py3.10-poc-llm-infer:v1.2.3 | 支持vllm reasoning output |  2025.03.04|
mr-bi150-4.1.3-aarch64-ubuntu20.04-py3.10-poc-llm-infer:v1.2.2 | (支持qwen3稠密模型和glm4, 支持vllm0.7.3 + qwen3 patch)  | 2025.05.20|
mr-bi150-4.3.0.llm-x86-ubuntu20.04-py3.10-poc-llm-infer:v1.2.3 | 升级SDK4.3.0 支持vllm0.8.3|  2025.07.14|
mr-bi150-4.3.6.llm-aarch64-ubuntu20.04-py3.10-poc-llm-infer:v1.2.3|SDK4.3.0 支持vllm0.8.3 | 2025.07.14
mr-bi150-4.4.0-x86-ubuntu20.04-py3.10-poc-llm-infer_v1.2.3|SDK4.4.0 支持vllm0.11.2 | 2026.03.09
mr-bi150-4.4.0-x86-ubuntu20.04-py3.10-poc-llm-infer_v1.2.4|SDK4.4.0 支持vllm0.17.0 支持MTP功能 | 2026.05.28
mr-bi150-4.4.0-aarch64-ubuntu20.04-py3.10-poc-llm-infer:v1.2.4|SDK4.4.0 支持vllm0.17.0 支持MTP功能 | 2026.05.28
mr-bi150-4.4.0-x86-ubuntu20.04-py3.10-poc-llm-infer_v1.2.5|Qwen3.5/3.6系列性能优化 | 2026.07.16
mr-bi150-4.4.0-aarch64-ubuntu20.04-py3.10-poc-llm-infer:v1.2.5|Qwen3.5/3.6系列性能优化 | 2026.07.16