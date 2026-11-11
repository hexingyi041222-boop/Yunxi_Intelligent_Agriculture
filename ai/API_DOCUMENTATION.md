# YunXi 植物识别模型服务接口文档

## 1. 服务说明

YunXi 模型服务通过植物图片和用户问题判断调用范围：

| 用户意图 | `intent` | 调用模型 | 返回内容 |
| --- | --- | --- | --- |
| 询问植物类型 | `type` | Type | 植物类型 |
| 询问植物病害 | `disease` | Disease | 病害、原因和处理建议 |
| 同时询问类型和病害 | `both` | Type、Disease | 植物类型、病害、原因和处理建议 |

模型采用按需加载方式。服务启动后，第一次调用某个模型时需要额外等待模型加载。

## 2. 服务地址

测试环境：

```text
http://127.0.0.1:8000
```

局域网或服务器部署时：

```text
http://<模型服务器IP>:8000
```

启动命令：

```powershell
cd D:\YunXi
.\.venv\Scripts\python.exe -m uvicorn api_service:app --host 0.0.0.0 --port 8000
```

当前模型不适合启动多个 worker，也不要使用 `--reload`。每个进程都会独立加载模型并占用大量内存。

## 3. 植物识别接口

### 3.1 基本信息

```http
POST /predict
Content-Type: multipart/form-data
```

完整地址：

```text
http://<模型服务器IP>:8000/predict
```

### 3.2 请求参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `image` | File | 是 | 植物图片，建议使用 JPG、JPEG 或 PNG |
| `question` | String | 是 | 用户提出的植物类型或植物病害问题 |

问题示例：

| 问题 | 预期 `intent` |
| --- | --- |
| `这是什么植物？` | `type` |
| `这是什么花？` | `type` |
| `叶子发黄是什么病？` | `disease` |
| `这朵花怎么了？` | `disease` |
| `这是什么花？它怎么了？` | `both` |
| `这是哪种树？有没有病？` | `both` |

问题为空或无法判断是类型、病害还是两者时，接口返回 HTTP 400。

### 3.3 成功响应

HTTP 状态码：`200 OK`

公共字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | String | 固定为 `success` |
| `intent` | String | `type`、`disease` 或 `both` |
| `data` | Object | 模型识别结果，字段取决于 `intent` |
| `processing_time_ms` | Number | 本次处理耗时，单位为毫秒 |
| `timestamp` | String | 服务响应时间，ISO 8601 格式 |

#### 仅识别植物类型

```json
{
  "status": "success",
  "intent": "type",
  "data": {
    "plant_type": "月季"
  },
  "processing_time_ms": 45231.67,
  "timestamp": "2026-08-12T11:00:00.000000"
}
```

#### 仅识别植物病害

```json
{
  "status": "success",
  "intent": "disease",
  "data": {
    "disease": "健康",
    "cause": "无病害",
    "treatment": "继续正常养护即可"
  },
  "processing_time_ms": 85076.23,
  "timestamp": "2026-08-12T11:00:00.000000"
}
```

#### 同时识别植物类型和病害

```json
{
  "status": "success",
  "intent": "both",
  "data": {
    "plant_type": "月季",
    "disease": "健康",
    "cause": "无病害",
    "treatment": "继续正常养护即可"
  },
  "processing_time_ms": 130456.78,
  "timestamp": "2026-08-12T11:00:00.000000"
}
```

`data` 字段对应关系：

| `intent` | `data` 字段 |
| --- | --- |
| `type` | `plant_type` |
| `disease` | `disease`、`cause`、`treatment` |
| `both` | `plant_type`、`disease`、`cause`、`treatment` |

### 3.4 失败响应

除参数校验错误（HTTP 422）外，失败响应的通用格式为：

```json
{
  "status": "error",
  "message": "错误描述信息",
  "timestamp": "2026-08-12T11:00:00.000000"
}
```

常见状态码：

| HTTP 状态码 | 场景 |
| --- | --- |
| `400` | 图片格式不正确、问题为空或无法判断问题意图 |
| `422` | 缺少 `image` 或 `question` 表单字段 |
| `500` | 模型加载、图片解析或推理失败 |
| `503` | 模型服务尚未完成初始化 |

无法判断问题意图的响应示例：

```json
{
  "status": "error",
  "message": "无法判断问题意图，请明确询问植物类型、植物病害，或同时询问两者",
  "timestamp": "2026-08-12T11:00:00.000000"
}
```

缺少 `image` 或 `question` 时，FastAPI 返回 HTTP 422，响应结构为：

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "question"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

调用方应同时兼容通用错误格式中的 `message` 和 HTTP 422 格式中的 `detail`。

## 4. 调用示例

### 4.1 curl

Windows PowerShell：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/predict" `
  -F "image=@D:\YunXi\test_plant.jpg" `
  -F "question=这是什么花？它怎么了？"
```

Linux/macOS：

```bash
curl -X POST "http://127.0.0.1:8000/predict" \
  -F "image=@test_plant.jpg" \
  -F "question=这是什么花？它怎么了？"
```

### 4.2 Python

```python
import requests

url = "http://127.0.0.1:8000/predict"

with open("test_plant.jpg", "rb") as image_file:
    response = requests.post(
        url,
        files={
            "image": ("test_plant.jpg", image_file, "image/jpeg"),
        },
        data={
            "question": "这是什么花？它怎么了？",
        },
        timeout=300,
    )

response.raise_for_status()
result = response.json()
print(result)
```

### 4.3 Node.js 18+

```javascript
import { readFile } from "node:fs/promises";

const image = await readFile("test_plant.jpg");
const form = new FormData();

form.append(
  "image",
  new Blob([image], { type: "image/jpeg" }),
  "test_plant.jpg",
);
form.append("question", "这是什么花？它怎么了？");

const response = await fetch("http://127.0.0.1:8000/predict", {
  method: "POST",
  body: form,
  signal: AbortSignal.timeout(300_000),
});

const result = await response.json();
if (!response.ok) {
  throw new Error(result.message ?? `HTTP ${response.status}`);
}

console.log(result);
```

### 4.4 Java（Spring Boot）

```java
RestClient client = RestClient.create("http://127.0.0.1:8000");

MultipartBodyBuilder body = new MultipartBodyBuilder();
body.part("image", new FileSystemResource("test_plant.jpg"));
body.part("question", "这是什么花？它怎么了？");

String response = client.post()
    .uri("/predict")
    .contentType(MediaType.MULTIPART_FORM_DATA)
    .body(body.build())
    .retrieve()
    .body(String.class);
```

调用方 HTTP 客户端的读取超时应设置为至少 300 秒。

## 5. 健康检查接口

### 5.1 请求

```http
GET /health
```

示例：

```powershell
curl.exe "http://127.0.0.1:8000/health"
```

### 5.2 响应

```json
{
  "status": "healthy",
  "service_ready": true,
  "models": {
    "type_model": "not_loaded",
    "disease_model": "not_loaded"
  },
  "timestamp": "2026-08-12T11:00:00.000000"
}
```

模型状态：

| 状态 | 说明 |
| --- | --- |
| `not_loaded` | 尚未收到需要该模型的问题，模型未加载 |
| `loaded` | 模型已经加载，可继续接收对应请求 |

`not_loaded` 是正常状态，不代表服务异常。

## 6. 模型信息接口

### 6.1 请求

```http
GET /model/info
```

示例：

```powershell
curl.exe "http://127.0.0.1:8000/model/info"
```

### 6.2 响应

模型尚未加载时：

```json
{
  "models": {
    "type_model": {
      "path": "./Type",
      "device": null,
      "status": "not_loaded"
    },
    "disease_model": {
      "path": "./Disease",
      "device": null,
      "status": "not_loaded"
    }
  }
}
```

CPU 环境加载后，对应模型的 `device` 为 `cpu`，`status` 为 `loaded`。

## 7. 在线接口文档

服务启动后可访问：

```text
Swagger UI: http://<模型服务器IP>:8000/docs
OpenAPI JSON: http://<模型服务器IP>:8000/openapi.json
```

## 8. 对接约束

1. 当前环境使用 CPU 推理，单次请求可能需要 1 至 3 分钟，调用方超时必须不低于 300 秒。
2. 建议调用方串行提交预测请求，或在业务后端建立任务队列，避免多个大模型推理请求同时争抢内存和 CPU。
3. 建议图片不超过 10 MB；调用前应限制为 JPG、JPEG 或 PNG。
4. 服务应使用单进程、单 worker 运行，不要开启自动重载。
5. 第一次请求会包含模型加载时间，后续同类请求会复用已加载模型。
6. 当前接口没有身份认证。部署到公网前必须由反向代理或业务网关增加 HTTPS、访问令牌、IP 白名单和请求大小限制，不应直接暴露 8000 端口。

## 9. 联调检查清单

1. 模型服务执行 `GET /health` 返回 HTTP 200。
2. 调用方能够访问模型服务器 IP 和 TCP 8000 端口。
3. `/predict` 使用 `multipart/form-data`，字段名必须为 `image` 和 `question`。
4. 调用方读取超时设置为至少 300 秒。
5. 调用方根据 `intent` 判断 `data` 中存在的字段，不假设每次都有 `plant_type`。
6. 调用方正确处理 400、422、500 和 503 响应。
7. 正式部署前配置访问控制和 HTTPS。
