# -*- coding: utf-8 -*-
"""本地 OCR 模块：基于 macOS Vision 框架，识别身份证照片/PDF、企查查截图。

特点：
- 全程本地识别，证件信息不上传任何服务器；
- PDF 先以 3 倍分辨率渲染成 PNG 再识别，保证扫描件清晰度。
"""
import os
import tempfile

from Foundation import NSURL
import Quartz
import Vision


def _cgimage_from_file(path):
    """将图片文件读为 CGImage。"""
    url = NSURL.fileURLWithPath_(os.path.abspath(path))
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if not src:
        return None
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def pdf_to_images(path, scale=3.0, max_pages=4):
    """将 PDF 每页渲染为高清 PNG，返回临时文件路径列表。"""
    url = NSURL.fileURLWithPath_(os.path.abspath(path))
    doc = Quartz.CGPDFDocumentCreateWithURL(url)
    if not doc:
        return []
    n = Quartz.CGPDFDocumentGetNumberOfPages(doc)
    out = []
    for i in range(1, min(n, max_pages) + 1):
        page = Quartz.CGPDFDocumentGetPage(doc, i)
        if page is None:
            continue
        rect = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        w = max(1, int(rect.size.width * scale))
        h = max(1, int(rect.size.height * scale))
        cs = Quartz.CGColorSpaceCreateDeviceRGB()
        ctx = Quartz.CGBitmapContextCreate(
            None, w, h, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast)
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
        Quartz.CGContextScaleCTM(ctx, scale, scale)
        Quartz.CGContextTranslateCTM(ctx, -rect.origin.x, -rect.origin.y)
        Quartz.CGContextDrawPDFPage(ctx, page)
        img = Quartz.CGBitmapContextCreateImage(ctx)
        if img is None:
            continue
        tmp = tempfile.mktemp(suffix=".png")
        out_url = NSURL.fileURLWithPath_(tmp)
        dest = Quartz.CGImageDestinationCreateWithURL(out_url, "public.png", 1, None)
        if dest is None:
            continue
        Quartz.CGImageDestinationAddImage(dest, img, None)
        Quartz.CGImageDestinationFinalize(dest)
        out.append(tmp)
    return out


def recognize_image(path):
    """对单张图片执行中文 OCR，返回识别出的文本行列表。"""
    cg = _cgimage_from_file(path)
    if cg is None:
        return []
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    try:
        req.setRecognitionLanguages_(["zh-Hans", "en-US"])
    except Exception:
        pass
    try:
        req.setUsesLanguageCorrection_(True)
    except Exception:
        pass
    try:
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    except Exception:
        pass
    handler.performRequests_error_([req], None)
    lines = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if cand:
            lines.append(cand[0].string())
    return lines


def ocr_file(path):
    """入口：图片或 PDF 均可，返回全部识别文本行。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        imgs = pdf_to_images(path)
        lines = []
        for im in imgs:
            lines.extend(recognize_image(im))
            try:
                os.remove(im)
            except OSError:
                pass
        return lines
    return recognize_image(path)
