import torch
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
from PIL import Image
import time
import logging
import json
import re
import sys
import os
import traceback
from threading import Lock

# 配置日志 - 修复GBK编码问题
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('plant_service.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_model_path(model_path: str) -> str:
    """Resolve bundled model paths independently of the process working directory."""
    if os.path.isabs(model_path):
        return model_path
    return os.path.abspath(os.path.join(PROJECT_DIR, model_path))


def _load_qwen_vl(model_path: str, device: str):
    # Both bundled models are stored in FP16. Keeping that dtype is essential:
    # converting two 7.5 GB checkpoints to FP32 would exceed typical system RAM.
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_path,
        dtype=torch.float16,
        trust_remote_code=True,
    )
    return model.to(device).eval()


def _prepare_inputs(processor, prompt, image: Image.Image, device: str):
    """Build both text tokens and Qwen2.5-VL image tensors."""
    text = processor.apply_chat_template(
        prompt,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = processor(
        text=[text],
        images=[image.convert("RGB")],
        padding=True,
        return_tensors="pt",
    )
    return inputs.to(device)


def _decode_generated(processor, inputs, outputs) -> str:
    """Decode generated tokens only, excluding the input conversation."""
    input_length = inputs["input_ids"].shape[1]
    generated_ids = outputs[:, input_length:]
    return processor.batch_decode(
        generated_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()


class PlantTypeModel:
    """植物类型识别模型 - 使用Qwen2.5-VL"""

    def __init__(self, model_path="./Type"):
        model_path = _resolve_model_path(model_path)
        logger.info("=" * 50)
        logger.info(f"正在加载植物类型识别模型，路径: {model_path}")

        # 检查模型路径是否存在
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"模型路径不存在: {model_path}")

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Type模型使用设备: {self.device}")
        logger.info(f"PyTorch版本: {torch.__version__}")
        if self.device == "cuda":
            logger.info(f"CUDA版本: {torch.version.cuda}")
            logger.info(f"GPU数量: {torch.cuda.device_count()}")
        else:
            logger.warning("未检测到CUDA，将使用CPU和FP16加载；推理速度会明显慢于独立显卡")

        try:
            # Qwen2.5-VL 使用 AutoProcessor 和特定的模型加载方式
            logger.info("开始加载Type模型处理器...")
            self.processor = AutoProcessor.from_pretrained(
                model_path,
                trust_remote_code=True
            )
            logger.info("Type模型处理器加载完成")

            logger.info("开始加载Type模型权重...")
            self.model = _load_qwen_vl(model_path, self.device)
            logger.info("Type模型权重加载完成")
            logger.info("植物类型识别模型加载完成！")
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"加载Type模型失败: {str(e)}")
            raise

    def predict(self, image: Image.Image) -> str:
        """
        识别植物类型
        """
        logger.info("开始识别植物类型...")
        # Qwen2.5-VL 使用特定的对话格式
        prompt = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": "请识别这张图片中的植物类型，只输出植物中文名称，不要有其他内容。"}
                ]
            }
        ]

        try:
            inputs = _prepare_inputs(self.processor, prompt, image, self.device)

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=50,
                    do_sample=False,
                    pad_token_id=(
                        self.processor.tokenizer.pad_token_id
                        or self.processor.tokenizer.eos_token_id
                    ),
                )

            response = _decode_generated(self.processor, inputs, outputs)

            # 清理输出，提取植物名称
            # 移除系统提示和用户提示
            plant_type = response.strip()
            # 如果有"assistant"标记，提取后面的内容
            if "assistant" in plant_type:
                plant_type = plant_type.split("assistant")[-1].strip()

            logger.info(f"植物类型识别结果: {plant_type}")
            return plant_type if plant_type else "未知植物"

        except Exception as e:
            logger.error(f"植物类型识别失败: {str(e)}")
            logger.error(traceback.format_exc())
            return "未知植物"


class PlantDiseaseModel:
    """植物病害识别模型 - 使用Qwen2.5-VL"""

    def __init__(self, model_path="./Disease"):
        model_path = _resolve_model_path(model_path)
        logger.info("=" * 50)
        logger.info(f"正在加载植物病害识别模型，路径: {model_path}")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"模型路径不存在: {model_path}")

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Disease模型使用设备: {self.device}")
        if self.device == "cpu":
            logger.warning("未检测到CUDA，将使用CPU和FP16加载；推理速度会明显慢于独立显卡")

        try:
            logger.info("开始加载Disease模型处理器...")
            self.processor = AutoProcessor.from_pretrained(
                model_path,
                trust_remote_code=True
            )
            logger.info("Disease模型处理器加载完成")

            logger.info("开始加载Disease模型权重...")
            self.model = _load_qwen_vl(model_path, self.device)
            logger.info("Disease模型权重加载完成")
            logger.info("植物病害识别模型加载完成！")
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"加载Disease模型失败: {str(e)}")
            raise

    def predict(self, image: Image.Image, plant_type: str = "") -> dict:
        """
        识别植物病害
        """
        logger.info(f"开始识别病害，植物类型: {plant_type}")

        # 构建提示词
        if plant_type and plant_type != "未知植物":
            text_prompt = f"""请分析这张{plant_type}的图片，识别是否存在病害问题。
按照以下JSON格式返回：
{{
    "disease": "病害名称（如果没有病害，输出'健康'）",
    "cause": "病害产生的原因分析（如果健康，输出'无病害'）",
    "treatment": "具体的养护建议和治疗方案（如果健康，输出'继续正常养护即可'）"
}}
只返回JSON，不要有其他内容。"""
        else:
            text_prompt = """请分析这张植物图片，识别是否存在病害问题。
按照以下JSON格式返回：
{
    "disease": "病害名称（如果没有病害，输出'健康'）",
    "cause": "病害产生的原因分析（如果健康，输出'无病害'）",
    "treatment": "具体的养护建议和治疗方案（如果健康，输出'继续正常养护即可'）"
}
只返回JSON，不要有其他内容。"""

        prompt = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": text_prompt}
                ]
            }
        ]

        try:
            inputs = _prepare_inputs(self.processor, prompt, image, self.device)

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=512,
                    do_sample=False,
                    pad_token_id=(
                        self.processor.tokenizer.pad_token_id
                        or self.processor.tokenizer.eos_token_id
                    ),
                )

            response = _decode_generated(self.processor, inputs, outputs)

            # 提取JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    disease_result = {
                        "disease": result.get("disease", "未知病害"),
                        "cause": result.get("cause", "无法确定原因"),
                        "treatment": result.get("treatment", "建议咨询专业人士")
                    }
                    logger.info(f"病害识别结果: {disease_result}")
                    return disease_result
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {e}")

            # 如果提取JSON失败，返回默认值
            return {
                "disease": "识别失败",
                "cause": "模型输出格式异常",
                "treatment": "请重新尝试"
            }

        except Exception as e:
            logger.error(f"病害识别失败: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "disease": "识别失败",
                "cause": f"解析错误: {str(e)}",
                "treatment": "请重新尝试"
            }


class PlantService:
    """Route user questions and lazily load only the required model."""

    TYPE_KEYWORDS = (
        "植物类型", "植物名称", "植物种类", "植物品种", "什么植物",
        "哪种植物", "哪类植物", "叫什么", "品种", "种类", "名称",
        "类型", "花名", "树种", "识别植物",
        "什么花", "哪种花", "哪类花", "是什么花",
        "什么树", "哪种树", "哪类树", "是什么树",
        "什么草", "哪种草", "哪类草", "是什么草",
        "辨认植物", "type", "species",
    )
    DISEASE_KEYWORDS = (
        "植物病害", "病害", "生病", "疾病", "健康", "症状", "病因",
        "原因", "治疗", "防治", "用药", "养护", "枯萎", "发黄",
        "黄叶", "虫害", "斑点", "腐烂", "霉", "叶子怎么", "怎么了",
        "有没有病", "什么病", "是否有病", "disease", "health",
    )

    def __init__(self, type_model_path="./Type", disease_model_path="./Disease"):
        logger.info("=" * 50)
        logger.info("开始初始化植物识别服务...")
        self.type_model_path = type_model_path
        self.disease_model_path = disease_model_path
        self.type_model = None
        self.disease_model = None
        self._type_model_lock = Lock()
        self._disease_model_lock = Lock()
        logger.info("植物识别服务初始化完成，模型将在收到问题后按需加载")
        logger.info("=" * 50)

    @classmethod
    def classify_intent(cls, question: str) -> str:
        """Return type, disease, or both according to the user's question."""
        normalized = re.sub(r"\s+", "", (question or "")).lower()
        if not normalized:
            raise ValueError("用户问题不能为空，请说明想识别植物类型、植物病害或两者")

        asks_type = any(keyword in normalized for keyword in cls.TYPE_KEYWORDS)
        asks_disease = any(keyword in normalized for keyword in cls.DISEASE_KEYWORDS)

        if asks_type and asks_disease:
            return "both"
        if asks_type:
            return "type"
        if asks_disease:
            return "disease"
        raise ValueError(
            "无法判断问题意图，请明确询问植物类型、植物病害，或同时询问两者"
        )

    def _get_type_model(self) -> PlantTypeModel:
        if self.type_model is None:
            with self._type_model_lock:
                if self.type_model is None:
                    self.type_model = PlantTypeModel(self.type_model_path)
        return self.type_model

    def _get_disease_model(self) -> PlantDiseaseModel:
        if self.disease_model is None:
            with self._disease_model_lock:
                if self.disease_model is None:
                    self.disease_model = PlantDiseaseModel(self.disease_model_path)
        return self.disease_model

    def model_status(self) -> dict:
        return {
            "type_model": "loaded" if self.type_model is not None else "not_loaded",
            "disease_model": "loaded" if self.disease_model is not None else "not_loaded",
        }

    def predict(self, image: Image.Image, question: str = "植物类型和植物病害") -> dict:
        """
        根据用户问题只调用植物类型模型、病害模型或两个模型。
        """
        start_time = time.time()
        intent = self.classify_intent(question)
        logger.info(f"问题意图: {intent}，用户问题: {question}")

        try:
            data = {}
            plant_type = ""

            if intent in ("type", "both"):
                logger.info("调用植物类型模型...")
                plant_type = self._get_type_model().predict(image)
                data["plant_type"] = plant_type

            if intent in ("disease", "both"):
                logger.info("调用植物病害模型...")
                disease_info = self._get_disease_model().predict(image, plant_type)
                data.update({
                    "disease": disease_info.get("disease", "未知"),
                    "cause": disease_info.get("cause", "未知"),
                    "treatment": disease_info.get("treatment", "建议咨询专业人士"),
                })

            processing_time = (time.time() - start_time) * 1000

            result = {
                "status": "success",
                "intent": intent,
                "data": data,
                "processing_time_ms": round(processing_time, 2)
            }

            logger.info(f"识别完成，耗时: {processing_time:.2f}ms")
            logger.info("=" * 50)
            return result

        except Exception as e:
            logger.error(f"识别过程出错: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "message": f"识别失败: {str(e)}"
            }


def test_with_sample_image():
    """使用示例图片测试服务"""
    logger.info("=" * 60)
    logger.info("开始测试植物识别服务")
    logger.info("=" * 60)

    try:
        # 1. 创建服务实例
        logger.info("1. 创建植物识别服务实例...")
        service = PlantService(
            type_model_path="./Type",
            disease_model_path="./Disease"
        )

        # 2. 加载测试图片
        logger.info("2. 加载测试图片...")
        test_image_path = "./test_plant.jpg"

        if not os.path.exists(test_image_path):
            logger.warning(f"测试图片不存在: {test_image_path}")
            logger.info("请将测试图片放到项目根目录，或修改 test_image_path 变量")
            logger.info("跳过测试，退出")
            return None
        else:
            image = Image.open(test_image_path).convert('RGB')
            logger.info(f"图片加载成功: {test_image_path}, 大小: {image.size}")

        # 3. 执行识别
        logger.info("3. 执行植物识别...")
        question = input("请输入问题（例如：这是什么植物？）：").strip()
        result = service.predict(image, question)

        # 4. 输出结果
        logger.info("=" * 60)
        logger.info("识别结果:")
        logger.info(json.dumps(result, ensure_ascii=False, indent=2))
        logger.info("=" * 60)

        if result.get("status") == "success":
            data = result["data"]
            print("\n" + "=" * 40)
            print("🌿 植物识别结果")
            print("=" * 40)
            if "plant_type" in data:
                print(f"植物名称: {data['plant_type']}")
            if "disease" in data:
                print(f"病害情况: {data['disease']}")
                print(f"原因分析: {data['cause']}")
                print(f"治疗建议: {data['treatment']}")
            print(f"处理耗时: {result['processing_time_ms']}ms")
            print("=" * 40)
        else:
            print(f"\n❌ 识别失败: {result.get('message', '未知错误')}")

        return result

    except Exception as e:
        logger.error(f"测试失败: {str(e)}")
        logger.error(traceback.format_exc())
        return None


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("🌱 植物识别服务启动 (Qwen2.5-VL)")
    print("=" * 60)
    print(f"Python版本: {sys.version}")
    print(f"工作目录: {os.getcwd()}")
    print(f"PyTorch版本: {torch.__version__}")
    print(f"CUDA可用: {torch.cuda.is_available()}")
    print("=" * 60 + "\n")

    # 运行测试z
    test_with_sample_image()


if __name__ == "__main__":
    main()
