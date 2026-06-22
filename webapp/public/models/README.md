# OCR 模型放置處

WebGPU 掃描需要兩個檔案放在此目錄（不隨 repo 提供，請自備）：

| 檔案 | 說明 |
|------|------|
| `rec.onnx` | PP-OCRv4 mobile **辨識**模型轉成 ONNX。輸入 `[1,3,48,320]`，輸出 `[1,T,C]` |
| `ppocr_keys_v1.txt` | 字元字典，每行一字元。**index 0 保留給 CTC blank**（程式會自動補上）|

## 取得方式

1. 從 PaddleOCR 下載 `PP-OCRv4_mobile_rec` 推論模型。
2. 用 `paddle2onnx` 轉成 `rec.onnx`：
   ```bash
   paddle2onnx --model_dir ./PP-OCRv4_mobile_rec_infer \
     --model_filename inference.pdmodel \
     --params_filename inference.pdiparams \
     --save_file rec.onnx --opset_version 13
   ```
3. 對應的 `ppocr_keys_v1.txt` 字典一併放入。

> 因 ROI 已裁切成卡片底部單行字串區，本專案**只用辨識模型、不需偵測模型**。
> 載入後 PWA Service Worker 會快取，之後可離線辨識。
