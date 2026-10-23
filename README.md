# ThemeGram Neon Studio

Termux uchun yengil, lokal video reklama generatori. Python + Pillow + FFmpeg; Chromium, GPU, bulut yoki pullik API talab qilinmaydi.

## Termux o‘rnatish

```bash
pkg update
pkg install python ffmpeg
termux-setup-storage
mkdir -p ~/ThemeGram-Neon-Studio
cd ~/ThemeGram-Neon-Studio
# GitHub'dan loyihani yuklab olish:
git clone https://github.com/cosmos634/ThemeGram-Neon-Studio-Complete-Automated-Video-Ad-Generator.git
cd ThemeGram-Neon-Studio-Complete-Automated-Video-Ad-Generator
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py --diagnose
python app.py
```

Brauzerda `http://127.0.0.1:8765` manzilini oching. Server faqat telefonning o‘zida ishlaydi.

## Birinchi video

Interfeysda sahnalar matnini o‘zgartiring, kerak bo‘lsa rasm yuklang, **Loyihani saqlash**, so‘ng **MP4 yaratish** tugmasini bosing. Videolar `exports/` ichiga yoziladi. Demo CLI:

```bash
python app.py --demo
```

## Android rasmlarini import qilish

1. Telefon brauzerida interfeysni oching.
2. Media bo‘limidagi fayl tanlash tugmasi orqali rasm yoki audio tanlang.
3. Fayl loyihaning `media/` papkasiga nusxalanadi; asl fayl o‘zgartirilmaydi.
4. Sahnadagi media ro‘yxatidan rasmni tanlab, saqlang va render qiling.

Termux fayllarga ruxsat so‘rasa `termux-setup-storage` buyrug‘ini bajaring. Brauzer fayl tanlagichi Android ruxsat bergan fayllarnigina ko‘rsatadi.

## Eslatma

- Birinchi ishga tushishda demo loyiha avtomatik yaratiladi.
- Render CPU orqali ishlaydi; telefonda 1080p uzoq davom etishi mumkin. Avval 480x854 preview ishlating.
- Video H.264 bilan yaratiladi. FFmpeg build'ida `libx264` bo‘lmasa, diagnostika xabar beradi.
- Audio qo‘shish ixtiyoriy; AAC mavjud bo‘lmasa, render xatolikni ochiq ko‘rsatadi.
- Namuna telefon ekranidagi tema ko‘rinishi — maket, haqiqiy ThemeGram skrinshoti emas.
- Ilova internetga server ochmaydi, token talab qilmaydi.
- Bu birinchi amaliy versiya: real-time timeline montaj emas, sahna asosidagi yengil generator.

## Diagnostika va muammolar

```bash
python app.py --diagnose
df -h "$HOME"
free -h
```

FFmpeg topilmasa: `pkg install ffmpeg`. Ruxsat xatosida loyiha papkasi yozish mumkin bo‘lgan joyda ekanini tekshiring. Render to‘xtasa `logs/app.log` ni ko‘ring; vaqtinchalik fayllar xato yuz berganda saqlanadi.
