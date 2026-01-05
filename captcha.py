import base64
import cv2
import numpy as np
import onnxruntime
from typing import List, Optional, Tuple
from constants import YOLO_MODEL_PATH, SIAMESE_MODEL_PATH


class Crack:
    def __init__(self):
        """初始化验证码破解器，预加载YOLO和Siamese模型"""
        self.big_img = None
        # 初始化时加载模型（仅加载一次）
        self.yolo_session = onnxruntime.InferenceSession(YOLO_MODEL_PATH)
        self.siamese_session = onnxruntime.InferenceSession(SIAMESE_MODEL_PATH)

    def read_base64_image(self, base64_string: str) -> np.ndarray:
        """
        将Base64字符串解码为OpenCV图像
        
        Args:
            base64_string: 图像的Base64编码字符串
            
        Returns:
            解码后的OpenCV图像（BGR格式）
        """
        img_data = base64.b64decode(base64_string)
        np_array = np.frombuffer(img_data, np.uint8)
        return cv2.imdecode(np_array, cv2.IMREAD_COLOR)

    def detect(self, big_img: str) -> Optional[List[List[int]]]:
        """
        使用YOLO模型检测验证码中的文字位置
        
        Args:
            big_img: 大图的Base64编码字符串
            
        Returns:
            检测到的边界框列表，每个框为[left, top, width, height]；检测失败返回None
        """
        confidence_thres = 0.7
        iou_thres = 0.7
        session = self.yolo_session
        model_inputs = session.get_inputs()
        self.big_img = self.read_base64_image(big_img)
        img_height, img_width = self.big_img.shape[:2]
        img = cv2.cvtColor(self.big_img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (512, 192))
        image_data = np.array(img) / 255.0
        image_data = np.transpose(image_data, (2, 0, 1))
        image_data = np.expand_dims(image_data, axis=0).astype(np.float32)
        input = {model_inputs[0].name: image_data}
        output = session.run(None, input)
        outputs = np.transpose(np.squeeze(output[0]))
        rows = outputs.shape[0]
        boxes, scores = [], []
        x_factor = img_width / 512
        y_factor = img_height / 192
        
        for i in range(rows):
            classes_scores = outputs[i][4:]
            max_score = np.amax(classes_scores)
            if max_score >= confidence_thres:
                x, y, w, h = outputs[i][0], outputs[i][1], outputs[i][2], outputs[i][3]
                left = int((x - w / 2) * x_factor)
                top = int((y - h / 2) * y_factor)
                width = int(w * x_factor)
                height = int(h * y_factor)
                boxes.append([left, top, width, height])
                scores.append(max_score)
                
        indices = cv2.dnn.NMSBoxes(boxes, scores, confidence_thres, iou_thres)
        new_boxes = [boxes[i] for i in indices]
        return new_boxes if len(new_boxes) == 5 else None

    def siamese(self, small_img: str, boxes: List[List[int]]) -> List[Tuple[int, int]]:
        """
        使用Siamese网络匹配验证码中的文字
        
        Args:
            small_img: 小图的Base64编码字符串
            boxes: 从大图中检测到的边界框列表
            
        Returns:
            匹配成功的位置坐标列表
        """
        session = self.siamese_session
        positions = [165, 200, 231, 265]
        result_list = []
        raw_image2 = self.read_base64_image(small_img)
        
        for x in positions:
            if len(result_list) == 4:
                break
            cropped = raw_image2[11:39, x:x+26]
            img2 = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
            img2 = cv2.resize(img2, (105, 105))
            image_data_2 = np.array(img2) / 255.0
            image_data_2 = np.transpose(image_data_2, (2, 0, 1))
            image_data_2 = np.expand_dims(image_data_2, axis=0).astype(np.float32)
            
            for box in boxes:
                raw_image1 = self.big_img[box[1]:box[1]+box[3]+2, box[0]:box[0]+box[2]+2]
                img1 = cv2.cvtColor(raw_image1, cv2.COLOR_BGR2RGB)
                img1 = cv2.resize(img1, (105, 105))
                image_data_1 = np.array(img1) / 255.0
                image_data_1 = np.transpose(image_data_1, (2, 0, 1))
                image_data_1 = np.expand_dims(image_data_1, axis=0).astype(np.float32)
                inputs = {'input': image_data_1, "input.53": image_data_2}
                output = session.run(None, inputs)
                output_sigmoid = 1 / (1 + np.exp(-output[0]))
                
                if output_sigmoid[0][0] >= 0.7:
                    result_list.append((box[0], box[1]))
                    break
                    
        return result_list