# 第三方组件与资源

此目录保留构建环境所用依赖的许可原文、版本和来源；其中部分组件只用于构建。
第三方组件的原有许可独立适用，本项目的非商业条款不限制其自身授予的权利。
Python、Tcl/Tk 与 PyInstaller bootloader 的许可/例外也随包保留。
ONNX Runtime、OpenCV、NumPy、Pillow 等自带的第三方声明包括在各自子目录。

OCR 使用 rapidocr-onnxruntime 1.4.4 随 wheel 提供的三份 ONNX 文件：
`ch_PP-OCRv4_det_infer.onnx`、`ch_PP-OCRv4_rec_infer.onnx`、
`ch_ppocr_mobile_v2.0_cls_infer.onnx`。来自 RapidOCR 对 PaddleOCR 模型的转换，
保留 Apache-2.0 许可和来源归属。实际模型哈希写入 release.json。

来源：
- https://github.com/RapidAI/RapidOCR
- https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/
- https://github.com/PaddlePaddle/PaddleOCR

`assets/templates` 是游戏界面局部截图裁剪，原游戏图像/文字/名称/商标归其权利人所有，
不属于本项目原创素材，不按本项目非商业许可授予额外权利。仅用于本地界面识别。
发行包不含游戏客户端、汉化 Mod、私人完整截图、运行记录或游戏账号资料。
`assets/selftest` 是本项目生成的纯文本 OCR 自检图，不含游戏截图。
