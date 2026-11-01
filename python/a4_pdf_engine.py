#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A4 PDF Motoru (NAPS2 Yöntemleri ile Tasarlanmıştır)
Tüm TIF, TIFF, JPG, JPEG, PNG, BMP, WEBP, PDF ve UDF belgelerini
A4 kağıt standartlarında (otomatik yönlendirme, oran korumalı sığdırma ve kenar boşluğu)
PDF'e dönüştürür ve tek bir PDF dosyasında birleştirir.
"""

import sys
import os
import io
import time
import subprocess
import tempfile
from typing import List, Tuple

from PIL import Image, ImageOps, ImageSequence
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import pypdf

# Standart A4 Ölçüleri (72 DPI - Point cinsinden)
A4_WIDTH, A4_HEIGHT = A4  # 595.2756, 841.8898
SAFE_MARGIN = 14.1732     # ~5 mm kenar boşluğu (yazıcı güvenli alanı)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
UYAP_CONVERT_BIN = os.path.join(BASE_DIR, "bin", "uyap-convert")


def notify(title: str, message: str, icon: str = "application-pdf"):
    """Sistem masaüstü bildirimi gönderir."""
    try:
        subprocess.run(["notify-send", "-i", icon, title, message], check=False)
    except Exception:
        pass
    print(f"[{title}] {message}")


def convert_udf_to_temp_pdf(udf_path: str) -> str:
    """UDF dosyasını UYAP Doküman Editörü resmi motoruyla geçici PDF'e dönüştürür."""
    tmp_pdf = tempfile.mktemp(suffix=".pdf")
    cmd = [UYAP_CONVERT_BIN, "--pdf", udf_path]
    
    # Hedef yolu udf_convert içinde oluşturulacak PDF
    base_pdf = os.path.splitext(udf_path)[0] + ".pdf"
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if os.path.exists(base_pdf) and os.path.getsize(base_pdf) > 0:
        return base_pdf
    else:
        raise RuntimeError(f"UDF dönüştürme başarısız: {res.stderr}")


def image_to_a4_pdf_pages(img_path: str) -> io.BytesIO:
    """
    Bir görsel dosyasını (tekil veya çok sayfalı TIFF) NAPS2 yöntemleriyle
    A4 sayfalarına basılmış bir PDF akışına dönüştürür.
    """
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer)

    with Image.open(img_path) as im:
        # Çok sayfalı TIFF ve tekil görseller için kareleri dolaş
        for frame_idx, frame in enumerate(ImageSequence.Iterator(im)):
            # EXIF yönlendirmesini uygula (yan/ters çekilmiş fotoğraflar için)
            frame_fixed = ImageOps.exif_transpose(frame)
            if frame_fixed is None:
                frame_fixed = frame.copy()

            # RGB formatına çevir (RGBA veya CMYK veya Indexed olanları standartlaştır)
            if frame_fixed.mode in ("RGBA", "LA", "P"):
                rgb_im = Image.new("RGB", frame_fixed.size, (255, 255, 255))
                if frame_fixed.mode == "RGBA":
                    rgb_im.paste(frame_fixed, mask=frame_fixed.split()[3])
                else:
                    rgb_im.paste(frame_fixed.convert("RGB"))
                frame_fixed = rgb_im
            elif frame_fixed.mode != "RGB":
                frame_fixed = frame_fixed.convert("RGB")

            img_w, img_h = frame_fixed.size

            # NAPS2 Otomatik Yönlendirme Kuralı:
            # Genişlik > Yükseklik ise Yatay A4, aksi halde Dikey A4
            if img_w > img_h:
                page_w, page_h = landscape(A4)
            else:
                page_w, page_h = A4

            c.setPageSize((page_w, page_h))

            # Yazdırılabilir alan ve oran korumalı ölçekleme (Fit to Page)
            avail_w = page_w - (2 * SAFE_MARGIN)
            avail_h = page_h - (2 * SAFE_MARGIN)

            scale = min(avail_w / img_w, avail_h / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale

            # Sayfa ortalama (Centering)
            pos_x = SAFE_MARGIN + (avail_w - draw_w) / 2.0
            pos_y = SAFE_MARGIN + (avail_h - draw_h) / 2.0

            # Görseli yüksek kalitede PDF akışına çiz
            img_byte_arr = io.BytesIO()
            frame_fixed.save(img_byte_arr, format="JPEG", quality=95)
            img_byte_arr.seek(0)
            img_reader = ImageReader(img_byte_arr)

            c.drawImage(img_reader, pos_x, pos_y, width=draw_w, height=draw_h)
            c.showPage()

    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer


def pdf_to_a4_pdf_pages(pdf_path: str) -> pypdf.PdfReader:
    """
    Girdi PDF dosyasının her sayfasını inceler.
    Zaten A4 ise doğrudan korur; farklı boyuttaysa A4 sayfaya sığdırır.
    """
    reader = pypdf.PdfReader(pdf_path)
    writer = pypdf.PdfWriter()

    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)

        # Yaklaşık A4 kontrolü (Dikey veya Yatay %3 tolerans)
        is_portrait_a4 = abs(w - A4_WIDTH) < 20 and abs(h - A4_HEIGHT) < 20
        is_landscape_a4 = abs(w - A4_HEIGHT) < 20 and abs(h - A4_WIDTH) < 20

        if is_portrait_a4 or is_landscape_a4:
            # Doğrudan vektör sayfa olarak ekle
            writer.add_page(page)
        else:
            # Standart dışı boyuttaki PDF sayfasını A4'e sığdır
            if w > h:
                target_w, target_h = landscape(A4)
            else:
                target_w, target_h = A4

            scale = min((target_w - 2 * SAFE_MARGIN) / w, (target_h - 2 * SAFE_MARGIN) / h)
            page.scale_by(scale)

            # Yeni A4 boş sayfa oluştur ve içeriği ortalayarak aktar
            new_page = writer.add_blank_page(width=target_w, height=target_h)
            new_w = float(page.mediabox.width)
            new_h = float(page.mediabox.height)
            tx = (target_w - new_w) / 2.0
            ty = (target_h - new_h) / 2.0
            new_page.merge_transformed_page(page, pypdf.Transformation().translate(tx, ty))

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    return pypdf.PdfReader(out_buf)


def process_single_file(file_path: str) -> pypdf.PdfReader:
    """Herhangi bir girdi dosyasını A4 formatlı PdfReader nesnesine çevirir."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".udf":
        print(f"[İŞLEM] UDF resmi motorla çözülüyor: {os.path.basename(file_path)}")
        pdf_path = convert_udf_to_temp_pdf(file_path)
        return pdf_to_a4_pdf_pages(pdf_path)

    elif ext == ".pdf":
        print(f"[İŞLEM] PDF sayfaları A4 standardına uyarlanıyor: {os.path.basename(file_path)}")
        return pdf_to_a4_pdf_pages(file_path)

    elif ext in (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        print(f"[İŞLEM] Görsel/TIFF A4 kağıt boyutuna basılıyor: {os.path.basename(file_path)}")
        buf = image_to_a4_pdf_pages(file_path)
        return pypdf.PdfReader(buf)

    else:
        raise ValueError(f"Desteklenmeyen dosya formatı: {ext}")


def convert_all_to_a4_pdf(files: List[str]):
    """Seçilen tüm dosyaları ayrı ayrı A4 PDF'e dönüştürür."""
    success_count = 0
    fail_count = 0
    last_file = ""

    for f in files:
        try:
            if not os.path.isfile(f):
                continue

            base, ext = os.path.splitext(f)
            if ext.lower() == ".pdf":
                out_pdf = base + "_A4.pdf"
            else:
                out_pdf = base + ".pdf"

            reader = process_single_file(f)
            writer = pypdf.PdfWriter()
            for p in reader.pages:
                writer.add_page(p)

            with open(out_pdf, "wb") as out_f:
                writer.write(out_f)

            success_count += 1
            last_file = out_pdf
            print(f"[BAŞARILI] A4 PDF oluşturuldu ({len(reader.pages)} sayfa): {out_pdf}")
        except Exception as e:
            fail_count += 1
            print(f"[HATA] {f} işlenirken hata oluştu: {e}")

    if success_count > 0:
        if success_count == 1:
            notify("A4 PDF Dönüştürme Tamamlandı", f"{os.path.basename(last_file)} oluşturuldu.")
        else:
            notify("A4 PDF Dönüştürme Tamamlandı", f"{success_count} dosya A4 PDF formatına dönüştürüldü.")
    else:
        notify("Dönüştürme Başarısız", "Hiçbir dosya dönüştürülemedi.", "dialog-error")


def merge_all_to_single_pdf(files: List[str], output_path: str = None):
    """Seçilen tüm dosyaları sırasıyla tek bir A4 PDF dosyasında birleştirir."""
    if not files:
        return

    first_dir = os.path.dirname(os.path.abspath(files[0]))
    if not output_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(first_dir, f"Birlestirilmis_Belge_{timestamp}.pdf")

    writer = pypdf.PdfWriter()
    total_pages = 0
    processed_files = 0

    for f in files:
        try:
            if not os.path.isfile(f):
                continue
            reader = process_single_file(f)
            for page in reader.pages:
                writer.add_page(page)
                total_pages += 1
            processed_files += 1
        except Exception as e:
            print(f"[UYARI] {f} birleştirmeye eklenemedi: {e}")

    if total_pages > 0:
        with open(output_path, "wb") as out_f:
            writer.write(out_f)
        print(f"[BAŞARILI] {processed_files} dosya ({total_pages} sayfa) birleştirildi: {output_path}")
        notify("Tek PDF'de Birleştirildi", f"{processed_files} dosya ({total_pages} sayfa) birleştirildi:\n{os.path.basename(output_path)}")
    else:
        notify("Birleştirme Başarısız", "Birleştirilecek sayfa bulunamadı.", "dialog-error")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Kullanım: a4_pdf_engine.py <--convert|--merge> <dosyalar...>")
        sys.exit(1)

    action = sys.argv[1]
    input_files = sys.argv[2:]

    if action == "--convert":
        convert_all_to_a4_pdf(input_files)
    elif action == "--merge":
        merge_all_to_single_pdf(input_files)
    else:
        print(f"Bilinmeyen eylem: {action}")
        sys.exit(2)
