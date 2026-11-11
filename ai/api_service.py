from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
import io
import os
import logging
from datetime import datetime
from dotenv import load_dotenv
import uvicorn

from model_loader import PlantService

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="植物识别API",
    description="基于双模型的植物类型和病害识别服务",
    version="2.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局服务实例
plant_service = None


@app.on_event("startup")
async def startup_event():
    """
    服务启动时加载模型
    """
    global plant_service
    logger.info("正在初始化植物识别服务...")
    try:
        plant_service = PlantService(
            type_model_path="./Type",
            disease_model_path="./Disease"
        )
        logger.info("植物识别服务初始化成功！")
    except Exception as e:
        logger.error(f"服务初始化失败: {str(e)}")
        raise e


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "植物识别API",
        "version": "2.0.0",
        "status": "running",
        "models": {
            "type_model": "植物类型识别",
            "disease_model": "植物病害识别"
        },
        "endpoints": {
            "/predict": "POST - 上传图片进行识别",
            "/health": "GET - 健康检查",
            "/model/info": "GET - 模型信息"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    global plant_service
    model_status = plant_service.model_status() if plant_service else {}
    return {
        "status": "healthy",
        "service_ready": plant_service is not None,
        "models": model_status,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/model/info")
async def model_info():
    """获取模型信息"""
    global plant_service
    if plant_service is None:
        raise HTTPException(status_code=503, detail="服务未就绪")

    return {
        "models": {
            "type_model": {
                "path": "./Type",
                "device": plant_service.type_model.device if plant_service.type_model else None,
                "status": plant_service.model_status()["type_model"]
            },
            "disease_model": {
                "path": "./Disease",
                "device": plant_service.disease_model.device if plant_service.disease_model else None,
                "status": plant_service.model_status()["disease_model"]
            }
        }
    }


@app.post("/predict")
async def predict(
        image: UploadFile = File(..., description="植物图片"),
        question: str = Form(..., description="用户想询问的植物问题")
):
    """
    植物识别接口

    上传植物图片和用户问题，服务会按问题意图调用所需模型并返回：
    - 植物类型
    - 病害名称
    - 病害原因
    - 养护建议
    """
    global plant_service

    # 验证服务是否就绪
    if plant_service is None:
        raise HTTPException(status_code=503, detail="服务未就绪，请稍后重试")

    # 验证图片格式
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="请上传图片文件（支持jpg、png等格式）"
        )

    try:
        # 读取图片
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))

        # 转换RGB
        if img.mode != "RGB":
            img = img.convert("RGB")

        # 记录请求日志
        logger.info(
            f"收到识别请求: {image.filename}, 大小: {len(contents)} bytes, "
            f"问题: {question}"
        )

        # 调用识别服务
        try:
            result = plant_service.predict(img, question)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 如果出错
        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result["message"])

        # 返回成功结果
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "intent": result["intent"],
                "data": result["data"],
                "processing_time_ms": result["processing_time_ms"],
                "timestamp": datetime.now().isoformat()
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理请求失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


# 请求日志中间件
@app.middleware("http")
async def log_requests(request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    duration = (datetime.now() - start_time).total_seconds()

    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Duration: {duration:.2f}s"
    )
    return response


# 全局异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "message": exc.detail,
            "timestamp": datetime.now().isoformat()
        }
    )


if __name__ == "__main__":
    uvicorn.run(
        "api_service:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
