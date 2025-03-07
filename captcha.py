import base64
import cv2
import numpy as np
import onnxruntime


class Crack:
    def __init__(self):
        self.big_img = None

    def read_base64_image(self, base64_string):
        """将Base64字符串解码为OpenCV图像"""
        img_data = base64.b64decode(base64_string)
        np_array = np.frombuffer(img_data, np.uint8)
        return cv2.imdecode(np_array, cv2.IMREAD_COLOR)

    def detect(self, big_img):
        """使用YOLO模型检测验证码中的文字位置"""
        confidence_thres = 0.7
        iou_thres = 0.7
        session = onnxruntime.InferenceSession("./onnx/yolov8.onnx")
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
        return new_boxes if len(new_boxes) == 5 else False

    def siamese(self, small_img, boxes):
        """使用Siamese网络匹配验证码中的文字"""
        session = onnxruntime.InferenceSession("./onnx/siamese.onnx")
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
                    result_list.append([box[0], box[1]])
                    break
        return result_list