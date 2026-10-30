# ETAP Kilit

Windows ana makineden Pardus ETAP akıllı tahtaları yönetmek için kilit, izleme ve yönetim yazılımı.

## Klasörler
- `windows/`   – Windows yönetim programı (PyQt5) + gömülü sunucu
- `client/`    – Pardus ETAP tahta istemcisi (kurulum paketine programdan gömülür)
- `installer/` – Inno Setup betiği (Setup.exe)
- `.github/workflows/build.yml` – GitHub'da otomatik derleme

## Setup.exe'yi GitHub'da derleme
1. GitHub'da yeni (özel) bir depo açın (**New repository** → **Private** → **Create repository**), bu klasörün içeriğini yükleyin.
2. **Actions** → "Windows Kurulum Dosyası" → **Run workflow**.
3. İş bitince (≈5 dk) sayfanın altındaki **Artifacts → ETAPKilit-Kurulum** dosyasını indirin.

## İlk kullanım
1. Setup.exe'yi Windows ana makinede kurun, programı açın.
2. **Ayarlar**: okul adı, Pardus logosu, kilit ekranı arkaplanı, sunucu IP'si.
3. **Yetkilendirme**: ortak öğretmen kodunu öğretmenlere duyurun (öğretmen başına parola yok).
4. **Kurulum Paketi** → `.deb` oluşturun, tahtalara kurun: `sudo apt install ./etap-kilit_*.deb`
5. Tahtalar açılışta otomatik bağlanır ve **Tahtalar** sayfasında görünür.

## Öğretmen girişi (nasıl çalışır?)
- Tahta imzalı bir karekod gösterir. Telefon karekodu okutunca sayfa açılır.
- Öğretmen **ortak öğretmen kodunu** bir kez girer ve "bu telefonu hatırla"yı işaretler.
  Sonraki okutmalarda hiçbir şey yazmadan doğrudan 6 haneli PIN görür.
- PIN, tahtaya ve o karekoda özeldir, tek kullanımlıktır ve kısa sürede geçersiz olur.
- Kod sızarsa **Yetkilendirme → Yeni kod üret** veya **Kayıtlı telefonları sıfırla**.

## Harici karekod sayfası (PHP)
1. **Yetkilendirme → Karekod sayfası → Harici web sitesi (PHP)** seçin.
2. **PHP dosyalarını dışa aktar…** ile `etap-kod` klasörünü oluşturun, web sitenize yükleyin.
3. Sayfa adresini (`https://okulunuz.com/etap/kod.php`) yazıp **Kaydet**'e basın, **Test bağlantısını aç** ile deneyin.
4. Kod, okul adı veya süre değişince yalnızca `config.php` dosyasını yeniden yükleyin
   (program, dosyalar eskidiğinde sizi uyarır).

## Kaynaktan çalıştırma (geliştirme)
```
cd windows
pip install -r requirements.txt
python app.py
```
