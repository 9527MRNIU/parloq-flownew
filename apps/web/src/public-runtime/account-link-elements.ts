import {
  AsYouType,
  getCountries,
  getCountryCallingCode,
  parsePhoneNumberFromString,
  type CountryCode,
} from "libphonenumber-js/min";

type RuntimeConfig = {
  resolvedLocale?: string;
  defaultLocale?: string;
  supportedLocales?: string[];
  localizedCopy?: Record<string, string>;
  inAppBrowserMode?: "allow" | "guide_external";
  previewMode?: boolean;
  previewDevice?: "desktop" | "tablet" | "mobile";
};

type PairingHandle = {
  pairingCode: string;
  attemptId?: string;
  pairingStatus?: string;
  expiresAt?: string;
};

type BridgeError = Error & {
  code?: string;
  retryable?: boolean;
  status?: number;
};

type FunctionalCopy = {
  countryLabel: string;
  phoneLabel: string;
  phonePlaceholder: string;
  invalidPhone: string;
  submit: string;
  submitting: string;
  codeTitle: string;
  copyCode: string;
  copied: string;
  expires: string;
  openConsumer: string;
  openBusiness: string;
  appFallback: string;
  waiting: string;
  reconnecting: string;
  verified: string;
  expired: string;
  failed: string;
  cancelled: string;
  alreadyLinked: string;
  unavailable: string;
  inProgress: string;
  retry: string;
  initializing: string;
  initialized: string;
  initializationPartial: string;
};

type WhatsAppWebGuideCopy = {
  codeTitle: string;
  instructionOpenPattern: string;
  whatsappLabel: string;
  instructionPlatformPattern: string;
  menuLabel: string;
  settingsLabel: string;
  instructionLinkedPattern: string;
  linkedDevicesLabel: string;
  linkDeviceLabel: string;
  instructionEnterPattern: string;
  phoneLinkLabel: string;
};

type ResolvedCopy = FunctionalCopy & WhatsAppWebGuideCopy;

const COPY: Record<string, FunctionalCopy> = {
  en: {
    countryLabel: "Country or region", phoneLabel: "Mobile number", phonePlaceholder: "Enter your mobile number", invalidPhone: "Enter a valid mobile number.", submit: "Start linking", submitting: "Starting…", codeTitle: "Pairing code", copyCode: "Copy code", copied: "Copied", expires: "Expires in", openConsumer: "Open WhatsApp", openBusiness: "Open WhatsApp Business", appFallback: "If the app did not open, open it manually and keep this page available.", waiting: "Waiting for confirmation on your phone…", reconnecting: "Finishing the secure connection. Keep this page open…", verified: "Account linked successfully.", expired: "This code expired.", failed: "Account linking could not be completed.", cancelled: "Account linking was cancelled.", alreadyLinked: "This number is already linked and available. You do not need to link it again.", unavailable: "This number cannot be linked here.", inProgress: "This number already has a linking request in progress.", retry: "Use another number", initializing: "Account linked. Initializing account information…", initialized: "Account information is ready.", initializationPartial: "Account linked. Some information will continue syncing in the background.",
  },
  "zh-CN": {
    countryLabel: "国家或地区", phoneLabel: "手机号码", phonePlaceholder: "请输入手机号码", invalidPhone: "请输入有效的手机号码。", submit: "开始绑定", submitting: "正在开始…", codeTitle: "绑定码", copyCode: "复制绑定码", copied: "已复制", expires: "剩余时间", openConsumer: "打开 WhatsApp", openBusiness: "打开 WhatsApp Business", appFallback: "如果 App 没有打开，请手动打开，并保留当前页面。", waiting: "正在等待手机确认…", reconnecting: "正在完成安全连接，请保持页面打开…", verified: "账号绑定成功。", expired: "绑定码已过期。", failed: "账号绑定未完成。", cancelled: "账号绑定已取消。", alreadyLinked: "该号码已经绑定并可用，无需重复绑定。", unavailable: "该号码当前不能在这里绑定。", inProgress: "该号码已有正在进行的绑定请求。", retry: "使用其他号码", initializing: "账号已绑定，正在同步账号资料…", initialized: "账号资料已准备完成。", initializationPartial: "账号已绑定，部分资料将在后台继续同步。",
  },
  es: {
    countryLabel: "País o región", phoneLabel: "Número móvil", phonePlaceholder: "Introduce tu número móvil", invalidPhone: "Introduce un número móvil válido.", submit: "Iniciar vinculación", submitting: "Iniciando…", codeTitle: "Código de vinculación", copyCode: "Copiar código", copied: "Copiado", expires: "Caduca en", openConsumer: "Abrir WhatsApp", openBusiness: "Abrir WhatsApp Business", appFallback: "Si la aplicación no se abrió, ábrela manualmente y conserva esta página.", waiting: "Esperando confirmación en tu teléfono…", reconnecting: "Finalizando la conexión. Mantén esta página abierta…", verified: "Cuenta vinculada correctamente.", expired: "El código ha caducado.", failed: "No se pudo completar la vinculación.", cancelled: "La vinculación fue cancelada.", alreadyLinked: "Este número ya está vinculado y disponible.", unavailable: "Este número no se puede vincular aquí.", inProgress: "Este número ya tiene una vinculación en curso.", retry: "Usar otro número", initializing: "Cuenta vinculada. Sincronizando información…", initialized: "La información de la cuenta está lista.", initializationPartial: "Cuenta vinculada. Parte de la información seguirá sincronizándose.",
  },
  de: {
    countryLabel: "Land oder Region", phoneLabel: "Mobilnummer", phonePlaceholder: "Mobilnummer eingeben", invalidPhone: "Gib eine gültige Mobilnummer ein.", submit: "Verknüpfung starten", submitting: "Wird gestartet…", codeTitle: "Verknüpfungscode", copyCode: "Code kopieren", copied: "Kopiert", expires: "Läuft ab in", openConsumer: "WhatsApp öffnen", openBusiness: "WhatsApp Business öffnen", appFallback: "Falls die App nicht geöffnet wurde, öffne sie manuell und lasse diese Seite verfügbar.", waiting: "Warten auf Bestätigung am Telefon…", reconnecting: "Verbindung wird abgeschlossen. Seite geöffnet lassen…", verified: "Konto erfolgreich verknüpft.", expired: "Der Code ist abgelaufen.", failed: "Die Verknüpfung konnte nicht abgeschlossen werden.", cancelled: "Die Verknüpfung wurde abgebrochen.", alreadyLinked: "Diese Nummer ist bereits verknüpft und verfügbar.", unavailable: "Diese Nummer kann hier nicht verknüpft werden.", inProgress: "Für diese Nummer läuft bereits eine Verknüpfung.", retry: "Andere Nummer verwenden", initializing: "Konto verknüpft. Kontoinformationen werden synchronisiert…", initialized: "Kontoinformationen sind bereit.", initializationPartial: "Konto verknüpft. Einige Informationen werden im Hintergrund weiter synchronisiert.",
  },
  fr: {
    countryLabel: "Pays ou région", phoneLabel: "Numéro de mobile", phonePlaceholder: "Saisissez votre numéro", invalidPhone: "Saisissez un numéro de mobile valide.", submit: "Commencer l’association", submitting: "Démarrage…", codeTitle: "Code d’association", copyCode: "Copier le code", copied: "Copié", expires: "Expire dans", openConsumer: "Ouvrir WhatsApp", openBusiness: "Ouvrir WhatsApp Business", appFallback: "Si l’application ne s’est pas ouverte, ouvrez-la manuellement et gardez cette page disponible.", waiting: "En attente de confirmation sur votre téléphone…", reconnecting: "Finalisation de la connexion. Gardez cette page ouverte…", verified: "Compte associé avec succès.", expired: "Ce code a expiré.", failed: "L’association n’a pas pu être terminée.", cancelled: "L’association a été annulée.", alreadyLinked: "Ce numéro est déjà associé et disponible.", unavailable: "Ce numéro ne peut pas être associé ici.", inProgress: "Une association est déjà en cours pour ce numéro.", retry: "Utiliser un autre numéro", initializing: "Compte associé. Synchronisation des informations…", initialized: "Les informations du compte sont prêtes.", initializationPartial: "Compte associé. Certaines informations continueront à se synchroniser.",
  },
  "pt-BR": {
    countryLabel: "País ou região", phoneLabel: "Número de celular", phonePlaceholder: "Digite seu número", invalidPhone: "Digite um número de celular válido.", submit: "Iniciar vinculação", submitting: "Iniciando…", codeTitle: "Código de vinculação", copyCode: "Copiar código", copied: "Copiado", expires: "Expira em", openConsumer: "Abrir WhatsApp", openBusiness: "Abrir WhatsApp Business", appFallback: "Se o app não abriu, abra-o manualmente e mantenha esta página disponível.", waiting: "Aguardando confirmação no celular…", reconnecting: "Finalizando a conexão. Mantenha esta página aberta…", verified: "Conta vinculada com sucesso.", expired: "O código expirou.", failed: "Não foi possível concluir a vinculação.", cancelled: "A vinculação foi cancelada.", alreadyLinked: "Este número já está vinculado e disponível.", unavailable: "Este número não pode ser vinculado aqui.", inProgress: "Este número já possui uma vinculação em andamento.", retry: "Usar outro número", initializing: "Conta vinculada. Sincronizando informações…", initialized: "As informações da conta estão prontas.", initializationPartial: "Conta vinculada. Algumas informações continuarão sendo sincronizadas.",
  },
  ar: {
    countryLabel: "البلد أو المنطقة", phoneLabel: "رقم الهاتف", phonePlaceholder: "أدخل رقم الهاتف", invalidPhone: "أدخل رقم هاتف صالحًا.", submit: "بدء الربط", submitting: "جارٍ البدء…", codeTitle: "رمز الربط", copyCode: "نسخ الرمز", copied: "تم النسخ", expires: "تنتهي الصلاحية خلال", openConsumer: "فتح WhatsApp", openBusiness: "فتح WhatsApp Business", appFallback: "إذا لم يفتح التطبيق، افتحه يدويًا واترك هذه الصفحة متاحة.", waiting: "بانتظار التأكيد على هاتفك…", reconnecting: "جارٍ إكمال الاتصال. اترك الصفحة مفتوحة…", verified: "تم ربط الحساب بنجاح.", expired: "انتهت صلاحية الرمز.", failed: "تعذر إكمال ربط الحساب.", cancelled: "تم إلغاء ربط الحساب.", alreadyLinked: "هذا الرقم مرتبط ومتاح بالفعل.", unavailable: "لا يمكن ربط هذا الرقم هنا.", inProgress: "يوجد طلب ربط جارٍ لهذا الرقم.", retry: "استخدام رقم آخر", initializing: "تم ربط الحساب. جارٍ مزامنة المعلومات…", initialized: "معلومات الحساب جاهزة.", initializationPartial: "تم ربط الحساب. ستستمر مزامنة بعض المعلومات في الخلفية.",
  },
  id: {
    countryLabel: "Negara atau wilayah", phoneLabel: "Nomor ponsel", phonePlaceholder: "Masukkan nomor ponsel", invalidPhone: "Masukkan nomor ponsel yang valid.", submit: "Mulai menautkan", submitting: "Memulai…", codeTitle: "Kode penautan", copyCode: "Salin kode", copied: "Disalin", expires: "Berakhir dalam", openConsumer: "Buka WhatsApp", openBusiness: "Buka WhatsApp Business", appFallback: "Jika aplikasi tidak terbuka, buka secara manual dan biarkan halaman ini tersedia.", waiting: "Menunggu konfirmasi di ponsel…", reconnecting: "Menyelesaikan koneksi. Biarkan halaman ini terbuka…", verified: "Akun berhasil ditautkan.", expired: "Kode ini sudah kedaluwarsa.", failed: "Penautan akun tidak dapat diselesaikan.", cancelled: "Penautan akun dibatalkan.", alreadyLinked: "Nomor ini sudah tertaut dan tersedia.", unavailable: "Nomor ini tidak dapat ditautkan di sini.", inProgress: "Nomor ini sudah memiliki proses penautan.", retry: "Gunakan nomor lain", initializing: "Akun tertaut. Menyinkronkan informasi…", initialized: "Informasi akun siap.", initializationPartial: "Akun tertaut. Beberapa informasi akan terus disinkronkan.",
  },
  hi: {
    countryLabel: "देश या क्षेत्र", phoneLabel: "मोबाइल नंबर", phonePlaceholder: "मोबाइल नंबर दर्ज करें", invalidPhone: "मान्य मोबाइल नंबर दर्ज करें।", submit: "लिंक करना शुरू करें", submitting: "शुरू हो रहा है…", codeTitle: "लिंकिंग कोड", copyCode: "कोड कॉपी करें", copied: "कॉपी किया गया", expires: "समाप्त होने में", openConsumer: "WhatsApp खोलें", openBusiness: "WhatsApp Business खोलें", appFallback: "यदि ऐप नहीं खुला, तो उसे मैन्युअल रूप से खोलें और यह पेज उपलब्ध रखें।", waiting: "फ़ोन पर पुष्टि की प्रतीक्षा…", reconnecting: "कनेक्शन पूरा हो रहा है। पेज खुला रखें…", verified: "अकाउंट सफलतापूर्वक लिंक हो गया।", expired: "यह कोड समाप्त हो गया।", failed: "अकाउंट लिंक पूरा नहीं हो सका।", cancelled: "अकाउंट लिंक रद्द कर दिया गया।", alreadyLinked: "यह नंबर पहले से लिंक और उपलब्ध है।", unavailable: "यह नंबर यहाँ लिंक नहीं किया जा सकता।", inProgress: "इस नंबर के लिए लिंकिंग पहले से जारी है।", retry: "दूसरा नंबर इस्तेमाल करें", initializing: "अकाउंट लिंक हो गया। जानकारी सिंक हो रही है…", initialized: "अकाउंट की जानकारी तैयार है।", initializationPartial: "अकाउंट लिंक हो गया। कुछ जानकारी बैकग्राउंड में सिंक होती रहेगी।",
  },
  ru: {
    countryLabel: "Страна или регион", phoneLabel: "Номер мобильного телефона", phonePlaceholder: "Введите номер телефона", invalidPhone: "Введите действительный номер телефона.", submit: "Начать привязку", submitting: "Запуск…", codeTitle: "Код привязки", copyCode: "Копировать код", copied: "Скопировано", expires: "Истекает через", openConsumer: "Открыть WhatsApp", openBusiness: "Открыть WhatsApp Business", appFallback: "Если приложение не открылось, откройте его вручную и не закрывайте эту страницу.", waiting: "Ожидание подтверждения на телефоне…", reconnecting: "Завершаем защищённое подключение. Не закрывайте страницу…", verified: "Аккаунт успешно привязан.", expired: "Срок действия кода истёк.", failed: "Не удалось завершить привязку аккаунта.", cancelled: "Привязка аккаунта отменена.", alreadyLinked: "Этот номер уже привязан и доступен.", unavailable: "Этот номер нельзя привязать здесь.", inProgress: "Для этого номера уже выполняется привязка.", retry: "Использовать другой номер", initializing: "Аккаунт привязан. Выполняется синхронизация данных…", initialized: "Данные аккаунта готовы.", initializationPartial: "Аккаунт привязан. Часть данных продолжит синхронизироваться в фоне.",
  },
  ur: {
    countryLabel: "ملک یا خطہ", phoneLabel: "موبائل نمبر", phonePlaceholder: "اپنا موبائل نمبر درج کریں", invalidPhone: "درست موبائل نمبر درج کریں۔", submit: "لنک کرنا شروع کریں", submitting: "شروع ہو رہا ہے…", codeTitle: "لنک کرنے کا کوڈ", copyCode: "کوڈ کاپی کریں", copied: "کاپی ہو گیا", expires: "میعاد ختم ہونے میں", openConsumer: "WhatsApp کھولیں", openBusiness: "WhatsApp Business کھولیں", appFallback: "اگر ایپ نہ کھلے تو اسے خود کھولیں اور یہ صفحہ دستیاب رکھیں۔", waiting: "فون پر تصدیق کا انتظار ہے…", reconnecting: "محفوظ کنکشن مکمل ہو رہا ہے۔ صفحہ کھلا رکھیں…", verified: "اکاؤنٹ کامیابی سے لنک ہو گیا۔", expired: "اس کوڈ کی میعاد ختم ہو گئی۔", failed: "اکاؤنٹ لنک نہیں ہو سکا۔", cancelled: "اکاؤنٹ لنک کرنا منسوخ کر دیا گیا۔", alreadyLinked: "یہ نمبر پہلے سے لنک اور دستیاب ہے۔", unavailable: "یہ نمبر یہاں لنک نہیں کیا جا سکتا۔", inProgress: "اس نمبر کے لیے لنک کرنے کی درخواست پہلے سے جاری ہے۔", retry: "دوسرا نمبر استعمال کریں", initializing: "اکاؤنٹ لنک ہو گیا۔ معلومات سنک ہو رہی ہیں…", initialized: "اکاؤنٹ کی معلومات تیار ہیں۔", initializationPartial: "اکاؤنٹ لنک ہو گیا۔ کچھ معلومات پس منظر میں سنک ہوتی رہیں گی۔",
  },
  tr: {
    countryLabel: "Ülke veya bölge", phoneLabel: "Cep telefonu numarası", phonePlaceholder: "Telefon numaranızı girin", invalidPhone: "Geçerli bir telefon numarası girin.", submit: "Bağlamayı başlat", submitting: "Başlatılıyor…", codeTitle: "Bağlama kodu", copyCode: "Kodu kopyala", copied: "Kopyalandı", expires: "Kalan süre", openConsumer: "WhatsApp’ı aç", openBusiness: "WhatsApp Business’ı aç", appFallback: "Uygulama açılmadıysa elle açın ve bu sayfayı açık tutun.", waiting: "Telefonunuzda onay bekleniyor…", reconnecting: "Güvenli bağlantı tamamlanıyor. Sayfayı açık tutun…", verified: "Hesap başarıyla bağlandı.", expired: "Bu kodun süresi doldu.", failed: "Hesap bağlama tamamlanamadı.", cancelled: "Hesap bağlama iptal edildi.", alreadyLinked: "Bu numara zaten bağlı ve kullanılabilir.", unavailable: "Bu numara burada bağlanamaz.", inProgress: "Bu numara için zaten bir bağlama isteği var.", retry: "Başka bir numara kullan", initializing: "Hesap bağlandı. Bilgiler eşitleniyor…", initialized: "Hesap bilgileri hazır.", initializationPartial: "Hesap bağlandı. Bazı bilgiler arka planda eşitlenmeye devam edecek.",
  },
  fa: {
    countryLabel: "کشور یا منطقه", phoneLabel: "شماره تلفن همراه", phonePlaceholder: "شماره تلفن را وارد کنید", invalidPhone: "شماره تلفن معتبری وارد کنید.", submit: "شروع پیوند", submitting: "درحال شروع…", codeTitle: "کد پیوند", copyCode: "کپی کد", copied: "کپی شد", expires: "زمان باقی‌مانده", openConsumer: "باز کردن WhatsApp", openBusiness: "باز کردن WhatsApp Business", appFallback: "اگر برنامه باز نشد، آن را دستی باز کنید و این صفحه را نگه دارید.", waiting: "در انتظار تأیید در تلفن…", reconnecting: "درحال تکمیل اتصال امن. صفحه را باز نگه دارید…", verified: "حساب با موفقیت پیوند داده شد.", expired: "مهلت این کد تمام شد.", failed: "پیوند دادن حساب کامل نشد.", cancelled: "پیوند دادن حساب لغو شد.", alreadyLinked: "این شماره از قبل پیوند داده شده و در دسترس است.", unavailable: "این شماره را نمی‌توان اینجا پیوند داد.", inProgress: "برای این شماره درخواست پیوند درحال انجام است.", retry: "استفاده از شماره‌ای دیگر", initializing: "حساب پیوند داده شد. اطلاعات درحال همگام‌سازی است…", initialized: "اطلاعات حساب آماده است.", initializationPartial: "حساب پیوند داده شد. بخشی از اطلاعات در پس‌زمینه همگام می‌شود.",
  },
  bn: {
    countryLabel: "দেশ বা অঞ্চল", phoneLabel: "মোবাইল নম্বর", phonePlaceholder: "মোবাইল নম্বর লিখুন", invalidPhone: "সঠিক মোবাইল নম্বর লিখুন।", submit: "লিঙ্ক করা শুরু করুন", submitting: "শুরু হচ্ছে…", codeTitle: "লিঙ্ক করার কোড", copyCode: "কোড কপি করুন", copied: "কপি হয়েছে", expires: "মেয়াদ শেষ হবে", openConsumer: "WhatsApp খুলুন", openBusiness: "WhatsApp Business খুলুন", appFallback: "অ্যাপ না খুললে নিজে খুলুন এবং এই পেজটি খোলা রাখুন।", waiting: "ফোনে নিশ্চিতকরণের অপেক্ষা চলছে…", reconnecting: "নিরাপদ সংযোগ সম্পূর্ণ হচ্ছে। পেজটি খোলা রাখুন…", verified: "অ্যাকাউন্ট সফলভাবে লিঙ্ক হয়েছে।", expired: "এই কোডের মেয়াদ শেষ হয়েছে।", failed: "অ্যাকাউন্ট লিঙ্ক করা যায়নি।", cancelled: "অ্যাকাউন্ট লিঙ্ক করা বাতিল হয়েছে।", alreadyLinked: "এই নম্বরটি ইতিমধ্যে লিঙ্ক করা ও উপলভ্য।", unavailable: "এই নম্বরটি এখানে লিঙ্ক করা যাবে না।", inProgress: "এই নম্বরটির জন্য লিঙ্ক করার অনুরোধ চলছে।", retry: "অন্য নম্বর ব্যবহার করুন", initializing: "অ্যাকাউন্ট লিঙ্ক হয়েছে। তথ্য সিঙ্ক হচ্ছে…", initialized: "অ্যাকাউন্টের তথ্য প্রস্তুত।", initializationPartial: "অ্যাকাউন্ট লিঙ্ক হয়েছে। কিছু তথ্য ব্যাকগ্রাউন্ডে সিঙ্ক হতে থাকবে।",
  },
  it: {
    countryLabel: "Paese o area geografica", phoneLabel: "Numero di cellulare", phonePlaceholder: "Inserisci il numero di telefono", invalidPhone: "Inserisci un numero di telefono valido.", submit: "Avvia collegamento", submitting: "Avvio…", codeTitle: "Codice di collegamento", copyCode: "Copia codice", copied: "Copiato", expires: "Scade tra", openConsumer: "Apri WhatsApp", openBusiness: "Apri WhatsApp Business", appFallback: "Se l’app non si apre, aprila manualmente e mantieni disponibile questa pagina.", waiting: "In attesa della conferma sul telefono…", reconnecting: "Completamento della connessione sicura. Mantieni aperta la pagina…", verified: "Account collegato correttamente.", expired: "Il codice è scaduto.", failed: "Impossibile completare il collegamento.", cancelled: "Collegamento annullato.", alreadyLinked: "Questo numero è già collegato e disponibile.", unavailable: "Questo numero non può essere collegato qui.", inProgress: "Per questo numero è già in corso un collegamento.", retry: "Usa un altro numero", initializing: "Account collegato. Sincronizzazione delle informazioni…", initialized: "Le informazioni dell’account sono pronte.", initializationPartial: "Account collegato. Alcune informazioni continueranno a sincronizzarsi in background.",
  },
};

// Captured from the localized runtime resources served by web.whatsapp.com.
// See docs/whatsapp-phone-linking-copy-sources.md for the collection contract.
const WHATSAPP_WEB_GUIDE_COPY: Record<string, WhatsAppWebGuideCopy> = {
  en: { codeTitle: "Enter code on phone", instructionOpenPattern: "Open {=m2} on your phone", whatsappLabel: "WhatsApp", instructionPlatformPattern: "On Android tap {=m1} · On iPhone tap {=m5}", menuLabel: "Menu", settingsLabel: "Settings", instructionLinkedPattern: "Tap {=m1}, then {=m3}", linkedDevicesLabel: "Linked devices", linkDeviceLabel: "Link device", instructionEnterPattern: "Tap {=m1} and enter this code on your phone", phoneLinkLabel: "Link with phone number instead" },
  "zh-CN": { codeTitle: "在手机上输入代码", instructionOpenPattern: "在你的手机上打开{=m2}", whatsappLabel: "WhatsApp", instructionPlatformPattern: "在 Android 手机上，轻触{=m1} · 在 iPhone 上，轻触{=m5}", menuLabel: "“菜单”", settingsLabel: "“设置”", instructionLinkedPattern: "依次轻触“{=m1}”和“{=m3}”", linkedDevicesLabel: "已关联的设备", linkDeviceLabel: "关联设备", instructionEnterPattern: "轻触“{=m1}”，然后在你的手机上输入此验证码", phoneLinkLabel: "改用电话号码关联" },
  hi: { codeTitle: "फ़ोन पर कोड डालें", instructionOpenPattern: "अपने फ़ोन पर {=m2} खोलें", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Android यूज़र्स {=m1} पर टैप करें . iPhone यूज़र्स {=m5} पर टैप करें", menuLabel: "मेनू", settingsLabel: "सेटिंग्स", instructionLinkedPattern: "{=m1} पर टैप करके {=m3} पर टैप करें", linkedDevicesLabel: "लिंक किए गए डिवाइस", linkDeviceLabel: "डिवाइस लिंक करें", instructionEnterPattern: "{=m1} पर टैप करें और अपने फ़ोन पर यह कोड डालें", phoneLinkLabel: "या फ़ोन नंबर से लिंक करें" },
  id: { codeTitle: "Masukkan kode di telepon", instructionOpenPattern: "Buka {=m2} di telepon", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Di Android ketuk {=m1} · Di iPhone ketuk {=m5}", menuLabel: "Menu", settingsLabel: "Pengaturan", instructionLinkedPattern: "Ketuk {=m1}, lalu {=m3}", linkedDevicesLabel: "Perangkat tertaut", linkDeviceLabel: "Tautkan perangkat", instructionEnterPattern: "Ketuk {=m1}, lalu masukkan kode ini di telepon Anda", phoneLinkLabel: "Tautkan dengan nomor telepon saja" },
  "pt-BR": { codeTitle: "Insira o código no seu celular", instructionOpenPattern: "Abra o {=m2} no seu celular.", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Toque em {=m1} no Android ou em {=m5} no iPhone.", menuLabel: "Mais opções", settingsLabel: "Configurações", instructionLinkedPattern: "Toque em {=m1} e, em seguida, em {=m3}.", linkedDevicesLabel: "Dispositivos conectados", linkDeviceLabel: "Conectar dispositivo", instructionEnterPattern: "Toque em {=m1} e insira o código exibido no seu celular.", phoneLinkLabel: "Conectar com número de telefone" },
  es: { codeTitle: "Ingresa el código en el teléfono", instructionOpenPattern: "Abre {=m2} en tu teléfono.", whatsappLabel: "WhatsApp", instructionPlatformPattern: "En Android, toca {=m1}. En iPhone, toca {=m5}.", menuLabel: "Menú", settingsLabel: "Ajustes", instructionLinkedPattern: "Toca {=m1} y, luego, {=m3}.", linkedDevicesLabel: "Dispositivos vinculados", linkDeviceLabel: "Vincular dispositivo", instructionEnterPattern: "Toca {=m1} e ingresa este código en tu teléfono.", phoneLinkLabel: "Vincular con el número de teléfono" },
  ru: { codeTitle: "Введите код на телефоне", instructionOpenPattern: "Откройте {=m2} на своем телефоне", whatsappLabel: "WhatsApp", instructionPlatformPattern: "На Android нажмите {=m1} · На iPhone нажмите {=m5}", menuLabel: "Меню", settingsLabel: "Настройки", instructionLinkedPattern: "Нажмите {=m1}, затем {=m3}", linkedDevicesLabel: "Связанные устройства", linkDeviceLabel: "Связывание устройства", instructionEnterPattern: "Нажмите \"{=m1}\" и введите этот код на своем телефоне", phoneLinkLabel: "Связать по номеру телефона" },
  ur: { codeTitle: "فون پر کوڈ درج کریں", instructionOpenPattern: "اپنے فون پر {=m2} کھولیں", whatsappLabel: "‏‏WhatsApp", instructionPlatformPattern: "‏‏Android پر {=m1} پر ٹیپ کریں ۔ iPhone پر {=m5} پر ٹیپ کریں", menuLabel: "مینیو", settingsLabel: "سیٹنگز", instructionLinkedPattern: "‏‏{=m1}، پھر {=m3} پر ٹیپ کریں", linkedDevicesLabel: "لنک کردہ ڈیوائسز", linkDeviceLabel: "آلہ لنک کریں", instructionEnterPattern: "‏‏{=m1} پر ٹیپ کریں اور اس کوڈ کو اپنے فون پر درج کریں", phoneLinkLabel: "اس کی بجائے فون نمبر کے ذریعے لنک کریں" },
  de: { codeTitle: "Code auf dem Telefon eingeben", instructionOpenPattern: "Öffne {=m2} auf deinem Telefon.", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Tippe auf einem Android-Gerät auf {=m1} · Tippe auf einem iPhone auf {=m5}", menuLabel: "Menü", settingsLabel: "Einstellungen", instructionLinkedPattern: "Tippe auf {=m1} und dann auf {=m3}.", linkedDevicesLabel: "Verknüpfte Geräte", linkDeviceLabel: "Gerät hinzufügen", instructionEnterPattern: "Tippe auf {=m1} und gib diesen Code auf deinem Telefon ein.", phoneLinkLabel: "Gerät stattdessen via Telefonnummer verknüpfen" },
  tr: { codeTitle: "Kodu telefonunuza girin", instructionOpenPattern: "Telefonunuzda {=m2}'ı açın", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Android'de {=m1}, iPhone'da {=m5}'a dokunun", menuLabel: "Menü", settingsLabel: "Ayarlar", instructionLinkedPattern: "{=m1}'a, ardından {=m3}'ya dokunun", linkedDevicesLabel: "Bağlı cihazlar", linkDeviceLabel: "Cihaz bağla", instructionEnterPattern: "{=m1} seçeneğine dokunun ve bu kodu telefonunuza girin", phoneLinkLabel: "Telefon numarası kullanarak bağlayın" },
  ar: { codeTitle: "أدخل الكود على الهاتف", instructionOpenPattern: "افتح {=m2} على هاتفك", whatsappLabel: "واتساب", instructionPlatformPattern: "على جهاز Android، اضغط على {=m1} · على جهاز iPhone، اضغط على {=m5}", menuLabel: "القائمة", settingsLabel: "الإعدادات", instructionLinkedPattern: "اضغط على {=m1}، ثم على {=m3}", linkedDevicesLabel: "الأجهزة المرتبطة", linkDeviceLabel: "ربط جهاز", instructionEnterPattern: "اضغط على {=m1} وأدخل هذا الكود على هاتفك", phoneLinkLabel: "الربط برقم الهاتف بدلاً من ذلك" },
  fa: { codeTitle: "کد را در تلفن وارد کنید", instructionOpenPattern: "‏{=m2} را در تلفنتان باز کنید", whatsappLabel: "واتساپ", instructionPlatformPattern: "در Android روی {=m1} ضربه بزنید. در iPhone، روی {=m5} ضربه بزنید", menuLabel: "منو", settingsLabel: "تنظیمات", instructionLinkedPattern: "روی {=m1} و سپس روی {=m3} ضربه بزنید", linkedDevicesLabel: "دستگاه‌های پیوندشده", linkDeviceLabel: "پیوند دادن دستگاه", instructionEnterPattern: "روی {=m1} ضربه بزنید و این کد را در تلفنتان وارد کنید", phoneLinkLabel: "در عوض ازطریق شماره تلفن پیوند داده شود" },
  bn: { codeTitle: "ফোনে কোডটি লিখুন", instructionOpenPattern: "আপনার ফোনে {=m2} খুলুন", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Android-এ {=m1}-তে ট্যাপ করুন · iPhone-এ {=m5}-এ ট্যাপ করুন", menuLabel: "মেনু", settingsLabel: "সেটিংস", instructionLinkedPattern: "{=m1}-এ ট্যাপ করে {=m3}-এ ট্যাপ করুন", linkedDevicesLabel: "লিঙ্ক করা ডিভাইস", linkDeviceLabel: "ডিভাইস লিঙ্ক করুন", instructionEnterPattern: "{=m1}-এ ট্যাপ করুন এবং আপনার ফোনে এই কোডটি লিখুন", phoneLinkLabel: "পরিবর্তে ফোন নম্বর দিয়ে লিঙ্ক করুন" },
  it: { codeTitle: "Inserisci il codice sul telefono", instructionOpenPattern: "Apri {=m2} sul telefono.", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Su Android tocca {=m1} · Su iPhone tocca {=m5}", menuLabel: "Menu", settingsLabel: "Impostazioni", instructionLinkedPattern: "Tocca {=m1}, quindi {=m3}", linkedDevicesLabel: "Dispositivi collegati", linkDeviceLabel: "Collega dispositivo", instructionEnterPattern: "Tocca {=m1} e inserisci questo codice sul telefono.", phoneLinkLabel: "In alternativa, collega con il numero di telefono" },
  fr: { codeTitle: "Saisissez le code sur le téléphone", instructionOpenPattern: "Ouvrez {=m2} sur votre téléphone", whatsappLabel: "WhatsApp", instructionPlatformPattern: "Sur Android, appuyez sur {=m1} · Sur iPhone, appuyez sur {=m5}", menuLabel: "Menu", settingsLabel: "Paramètres", instructionLinkedPattern: "Appuyez sur {=m1}, puis sur {=m3}", linkedDevicesLabel: "Appareils connectés", linkDeviceLabel: "Connecter un appareil", instructionEnterPattern: "Appuyez sur {=m1} et saisissez ce code sur votre téléphone", phoneLinkLabel: "Connecter plutôt avec un numéro de téléphone" },
};

const runtimeConfig = (): RuntimeConfig => {
  const node = document.getElementById("promotion-runtime-config");
  if (!node) return {};
  try { return JSON.parse(node.textContent || "{}"); } catch { return {}; }
};

const resolvedLocale = () => runtimeConfig().resolvedLocale || runtimeConfig().defaultLocale || navigator.languages?.[0] || navigator.language || "en";

const functionalCopy = (): ResolvedCopy => {
  const locale = resolvedLocale();
  const base = locale.toLowerCase().split("-")[0];
  const exact = Object.keys(COPY).find((key) => key.toLowerCase() === locale.toLowerCase());
  const selected = (exact ? COPY[exact] : undefined) || COPY[base] || COPY.en;
  const guide = (exact ? WHATSAPP_WEB_GUIDE_COPY[exact] : undefined) || WHATSAPP_WEB_GUIDE_COPY[base] || WHATSAPP_WEB_GUIDE_COPY.en;
  const overrides = runtimeConfig().localizedCopy || {};
  const copy: ResolvedCopy = { ...COPY.en, ...selected, ...WHATSAPP_WEB_GUIDE_COPY.en, ...guide };
  for (const key of Object.keys(copy) as Array<keyof ResolvedCopy>) {
    const value = overrides[`accountLink.${key}`];
    if (typeof value === "string" && value.trim()) copy[key] = value;
  }
  return copy;
};

const browserCountry = (): CountryCode | undefined => {
  for (const language of navigator.languages?.length ? navigator.languages : [navigator.language]) {
    try {
      const locale = new Intl.Locale(language);
      const region = locale.region || locale.maximize().region;
      if (region && getCountries().includes(region as CountryCode)) return region as CountryCode;
    } catch { /* unsupported or malformed browser locale */ }
  }
  return undefined;
};

const LOCALE_NAMES: Record<string, string> = {
  en: "English",
  "zh-CN": "简体中文",
  hi: "हिन्दी",
  id: "Bahasa Indonesia",
  "pt-BR": "Português (Brasil)",
  es: "Español",
  ru: "Русский",
  ur: "اردو",
  de: "Deutsch",
  tr: "Türkçe",
  ar: "العربية",
  fa: "فارسی",
  bn: "বাংলা",
  it: "Italiano",
  fr: "Français",
};

const LANGUAGE_LABELS: Record<string, string> = {
  en: "Language", "zh-CN": "语言", hi: "भाषा", id: "Bahasa", "pt-BR": "Idioma",
  es: "Idioma", ru: "Язык", ur: "زبان", de: "Sprache", tr: "Dil", ar: "اللغة",
  fa: "زبان", bn: "ভাষা", it: "Lingua", fr: "Langue",
};

const matchingLocaleKey = (locale: string, values: string[]) =>
  values.find((value) => value.toLowerCase() === locale.toLowerCase());

const sharedStyle = `
  :host{box-sizing:border-box;color:inherit;font:inherit}:host([hidden]){display:none!important}*,*::before,*::after{box-sizing:border-box}
  button,input,select{font:inherit;color:inherit}button{cursor:pointer}button:disabled{cursor:not-allowed;opacity:.65}
  [hidden]{display:none!important}.sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
`;

class AccountLinkLocaleSwitcher extends HTMLElement {
  private root = this.attachShadow({ mode: "open" });
  private select?: HTMLSelectElement;
  private flow?: HTMLElement;
  private lock = () => { if (this.select) this.select.disabled = true; };
  private unlock = () => { if (this.select) this.select.disabled = false; };

  connectedCallback() {
    const config = runtimeConfig();
    const locales = Array.from(new Set(config.supportedLocales || [config.defaultLocale || "en"]));
    if (locales.length < 2) { this.hidden = true; return; }
    const resolved = matchingLocaleKey(resolvedLocale(), locales) || locales[0];
    const labelKey = matchingLocaleKey(resolved, Object.keys(LANGUAGE_LABELS)) || resolved.split("-")[0];
    const label = LANGUAGE_LABELS[labelKey] || LANGUAGE_LABELS.en;
    this.root.innerHTML = `<style>${sharedStyle}
      :host{display:block}.locale{display:flex;justify-content:flex-end;align-items:center;gap:.5rem}.icon{font-size:1rem;line-height:1}.label{font-size:.875rem;font-weight:600}.select{min-height:2.5rem;max-width:100%;border:1px solid var(--account-link-field-border,#cbd5e1);border-radius:var(--account-link-locale-radius,.65rem);background:var(--account-link-field-bg,transparent);padding:.45rem 2rem .45rem .65rem}
    </style><label class="locale" part="container"><span class="icon" aria-hidden="true">🌐</span><span class="label" part="label">${label}</span><select class="select" part="select" aria-label="${label}">${locales.map((locale) => `<option value="${locale}">${LOCALE_NAMES[locale] || locale}</option>`).join("")}</select></label>`;
    this.select = this.root.querySelector("select")!;
    this.select.value = resolved;
    this.select.addEventListener("change", () => {
      if (!this.select?.value) return;
      if (config.previewMode && window.parent !== window) {
        window.parent.postMessage(
          {
            type: "promotion-preview:locale-change",
            locale: this.select.value,
          },
          "*",
        );
        return;
      }
      const url = new URL(window.location.href);
      url.searchParams.set("lang", this.select.value);
      window.location.assign(url.toString());
    });
    this.flow = this.closest("account-link-flow") || undefined;
    this.flow?.addEventListener("account-link-pairing-started", this.lock);
    this.flow?.addEventListener("account-link-reset", this.unlock);
  }

  disconnectedCallback() {
    this.flow?.removeEventListener("account-link-pairing-started", this.lock);
    this.flow?.removeEventListener("account-link-reset", this.unlock);
  }
}

class PhoneNumberField extends HTMLElement {
  private root = this.attachShadow({ mode: "open" });
  private country?: CountryCode;
  private select!: HTMLSelectElement;
  private input!: HTMLInputElement;
  private prefixNode!: HTMLElement;
  private error!: HTMLElement;

  connectedCallback() {
    const copy = functionalCopy();
    const locale = resolvedLocale();
    const allowed = (this.getAttribute("allowed-countries") || "").split(",").map((item) => item.trim().toUpperCase()).filter(Boolean) as CountryCode[];
    const countries = (allowed.length ? allowed : getCountries()).filter((item) => getCountries().includes(item));
    this.country = browserCountry();
    if (!this.country || !countries.includes(this.country)) this.country = undefined;
    const names = new Intl.DisplayNames([locale], { type: "region" });
    const options = countries.map((country) => ({ country, name: names.of(country) || country, calling: getCountryCallingCode(country) })).sort((a, b) => a.name.localeCompare(b.name, locale));
    this.root.innerHTML = `<style>${sharedStyle}
      :host{display:block}.field{display:grid;gap:.45rem}.label{font-weight:600}.phone{display:grid;grid-template-columns:minmax(8.5rem,42%) 1fr;border:1px solid var(--account-link-field-border,#cbd5e1);border-radius:var(--account-link-field-radius,.75rem);background:var(--account-link-field-bg,transparent);overflow:hidden;min-height:3rem}.country{display:grid;grid-template-columns:1fr auto;align-items:center;border-inline-end:1px solid var(--account-link-field-border,#cbd5e1);padding-inline:.75rem}.country select{min-width:0;width:100%;border:0;background:transparent;outline:0}.prefix{font-variant-numeric:tabular-nums;opacity:.7}.phone input{width:100%;border:0;background:transparent;padding:.75rem;outline:0}.phone:focus-within{outline:2px solid var(--account-link-focus,#2563eb);outline-offset:2px}.error{min-height:1.25em;color:var(--account-link-error,#b91c1c);font-size:.875rem}
    </style><div class="field" part="field"><label class="label" part="label" for="phone-input">${copy.phoneLabel}</label><div class="phone" part="phone-shell"><label class="country" part="country-shell"><span class="sr">${copy.countryLabel}</span><select part="country-select" aria-label="${copy.countryLabel}"><option value="">${copy.countryLabel}</option>${options.map((item) => `<option value="${item.country}">${item.name} · ${item.calling}</option>`).join("")}</select><span class="prefix" part="country-prefix"></span></label><input part="phone-input" id="phone-input" type="tel" inputmode="tel" autocomplete="tel" placeholder="${copy.phonePlaceholder}" aria-describedby="phone-error"></div><p class="error" part="error" id="phone-error" role="alert"></p></div>`;
    this.select = this.root.querySelector("select")!;
    this.input = this.root.querySelector("input")!;
    this.prefixNode = this.root.querySelector(".prefix")!;
    this.error = this.root.querySelector(".error")!;
    this.select.value = this.country || "";
    this.updatePrefix();
    this.select.addEventListener("change", () => {
      this.country = this.select.value ? this.select.value as CountryCode : undefined;
      this.updatePrefix();
      this.setError("");
      this.input.focus();
    });
    this.input.addEventListener("input", () => this.formatInput());
  }

  private updatePrefix() { this.prefixNode.textContent = this.country ? getCountryCallingCode(this.country) : ""; }

  private formatInput() {
    const raw = this.input.value;
    if (raw.trim().startsWith("+")) {
      const parsed = parsePhoneNumberFromString(raw);
      if (parsed?.country) {
        this.country = parsed.country;
        this.select.value = parsed.country;
        this.updatePrefix();
        this.input.value = parsed.formatNational().replace(/^\+/, "");
        this.setError("");
        return;
      }
    }
    const digits = raw.replace(/\D/g, "");
    this.input.value = this.country ? new AsYouType(this.country).input(digits).replace(/^\+/, "") : digits;
    this.setError("");
  }

  getPhone(): { e164: string; country: CountryCode } | null {
    if (!this.country) return null;
    const parsed = parsePhoneNumberFromString(this.input.value, this.country);
    if (!parsed?.isPossible()) return null;
    return { e164: parsed.number, country: parsed.country || this.country };
  }

  setError(message: string) {
    if (!this.error || !this.input) return;
    this.error.textContent = message;
    this.input.setAttribute("aria-invalid", message ? "true" : "false");
  }

  reset() { if (this.input) { this.input.value = ""; this.setError(""); } }
}

class AccountLinkSubmit extends HTMLElement {
  private root = this.attachShadow({ mode: "open" });
  private button!: HTMLButtonElement;
  connectedCallback() {
    const copy = functionalCopy();
    this.root.innerHTML = `<style>${sharedStyle}:host{display:block}button{width:100%;min-height:3rem;border:0;border-radius:var(--account-link-action-radius,.75rem);background:var(--account-link-action-bg,#111827);color:var(--account-link-action-color,#fff);padding:.75rem 1rem;font-weight:700}</style><button part="button" type="button">${copy.submit}</button>`;
    this.button = this.root.querySelector("button")!;
    this.button.addEventListener("click", () => this.dispatchEvent(new CustomEvent("account-link-submit", { bubbles: true })));
  }
  setLoading(value: boolean) { if (this.button) { this.button.disabled = value; this.button.textContent = value ? functionalCopy().submitting : functionalCopy().submit; } }
}

class PairingCodePanel extends HTMLElement {
  private root = this.attachShadow({ mode: "open" });
  private code = "";
  private expiresAt?: number;
  private timer?: number;
  connectedCallback() {
    const copy = functionalCopy();
    this.root.innerHTML = `<style>${sharedStyle}:host{display:block}.panel{display:grid;gap:.75rem}.code{font:700 var(--account-link-code-size,2rem)/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.12em;word-break:break-all}.actions{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}button{min-height:2.75rem;padding:.6rem .9rem;border:1px solid currentColor;border-radius:var(--account-link-secondary-radius,.65rem);background:transparent}.expiry{opacity:.75;font-size:.875rem}</style><section class="panel" part="panel"><strong part="title">${copy.codeTitle}</strong><output class="code" part="code"></output><div class="actions" part="actions"><button part="copy-button" type="button">${copy.copyCode}</button><span class="expiry" part="expiry"></span></div></section>`;
    this.root.querySelector("button")!.addEventListener("click", () => void this.copy());
  }
  show(pairing: PairingHandle) {
    this.code = String(pairing.pairingCode || "");
    this.expiresAt = pairing.expiresAt ? Date.parse(pairing.expiresAt) : undefined;
    this.root.querySelector("output")!.textContent = this.code.replace(/(.{4})/g, "$1 ").trim();
    this.hidden = false;
    this.tick();
    if (this.timer) clearInterval(this.timer);
    this.timer = window.setInterval(() => this.tick(), 1000);
  }
  private tick() {
    const expiry = this.root.querySelector(".expiry");
    if (!expiry) return;
    if (!this.expiresAt || Number.isNaN(this.expiresAt)) { expiry.textContent = ""; return; }
    const seconds = Math.max(0, Math.ceil((this.expiresAt - Date.now()) / 1000));
    expiry.textContent = `${functionalCopy().expires} ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }
  private async copy() {
    if (!this.code) return;
    try {
      await navigator.clipboard.writeText(this.code.replace(/\s/g, ""));
    } catch {
      const input = document.createElement("textarea"); input.value = this.code.replace(/\s/g, ""); input.style.position = "fixed"; input.style.opacity = "0"; document.body.appendChild(input); input.select(); document.execCommand("copy"); input.remove();
    }
    const button = this.root.querySelector("button")!;
    button.textContent = functionalCopy().copied;
    window.setTimeout(() => { button.textContent = functionalCopy().copyCode; }, 1600);
  }
  reset() { if (this.timer) clearInterval(this.timer); this.timer = undefined; this.hidden = true; this.code = ""; }
}

const appGuideIcons = {
  whatsapp: `<span class="guide-icon whatsapp-icon" part="whatsapp-icon" aria-hidden="true"><svg viewBox="0 0 40 40" focusable="false"><rect width="40" height="40" rx="2" fill="#25D366"/><path fill="#fff" fill-rule="evenodd" clip-rule="evenodd" d="M7.16 19.89a12.88 12.88 0 0 1 22-9.07 12.72 12.72 0 0 1 3.78 9.08 12.88 12.88 0 0 1-18.9 11.34l-6.46 1.69a.42.42 0 0 1-.5-.52l1.72-6.26a12.76 12.76 0 0 1-1.64-6.26Zm12.89 10.55c-1.89 0-3.73-.5-5.34-1.46l-.39-.22-3.96 1.03 1.06-3.85-.25-.4A10.37 10.37 0 0 1 9.57 20a10.47 10.47 0 0 1 17.9-7.38A10.34 10.34 0 0 1 30.52 20c0 5.76-4.7 10.44-10.48 10.44Zm3.53-8.94a52.15 52.15 0 0 1 2.31 1.1c.22.12.37.19.43.3.08.13.08.76-.18 1.5-.26.73-1.51 1.4-2.12 1.5-.54.08-1.22.11-1.97-.13a17.9 17.9 0 0 1-1.79-.66c-2.93-1.28-4.92-4.15-5.3-4.7l-.05-.07c-.17-.23-1.28-1.72-1.28-3.27 0-1.45.71-2.21 1.04-2.57l.06-.06c.29-.32.63-.4.83-.4a12.4 12.4 0 0 1 .68.01c.18 0 .4 0 .63.55l.35.84c.27.66.56 1.4.62 1.5.07.16.13.34.02.55l-.04.1a1.8 1.8 0 0 1-.27.43 12.6 12.6 0 0 0-.47.55c-.16.16-.32.33-.14.65a9.5 9.5 0 0 0 1.74 2.19 8.08 8.08 0 0 0 2.52 1.56c.32.16.5.13.68-.08.19-.2.79-.92 1-1.23.2-.32.41-.27.7-.16Z"/></svg></span>`,
  menu: `<span class="guide-icon menu-icon" part="android-menu-icon" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path fill="currentColor" d="M12 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm0 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm0 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"/></svg></span>`,
  settings: `<span class="guide-icon settings-icon" part="iphone-settings-icon" aria-hidden="true"><svg viewBox="0 0 20 20" focusable="false"><path fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" d="M10.63 18.23h.05l.47.88c.1.2.27.28.5.25a.44.44 0 0 0 .38-.4l.15-1c.43-.11.86-.28 1.28-.46l.73.65c.16.16.35.18.57.07.18-.1.25-.28.21-.51l-.2-.98c.36-.25.72-.54 1.05-.87l.9.38c.21.1.4.05.57-.14.14-.16.15-.36.03-.55l-.53-.85c.27-.37.48-.77.68-1.19l1 .05c.22.02.4-.1.46-.3a.5.5 0 0 0-.16-.55l-.78-.61c.11-.43.2-.88.24-1.35l.94-.3c.21-.08.33-.23.33-.46 0-.22-.12-.37-.33-.45l-.94-.3a7.75 7.75 0 0 0-.24-1.35l.78-.62c.17-.12.22-.31.16-.52a.44.44 0 0 0-.46-.32l-1 .05c-.2-.43-.41-.82-.68-1.19l.53-.85a.41.41 0 0 0-.03-.54c-.17-.2-.36-.23-.57-.15l-.9.38a8.38 8.38 0 0 0-1.05-.87l.2-.97c.04-.23-.03-.42-.21-.51-.2-.1-.37-.1-.51.01l-.8.7a8.55 8.55 0 0 0-1.27-.46l-.15-.98c-.03-.23-.16-.38-.38-.41-.23-.03-.4.06-.5.24l-.47.89-.45-.03H10l-.62.02h-.07L8.85.89a.44.44 0 0 0-.5-.25c-.22.03-.36.18-.39.4l-.14.98a8.4 8.4 0 0 0-1.28.47l-.73-.65c-.17-.15-.36-.18-.57-.06-.19.1-.25.28-.21.51l.2.97c-.37.25-.73.55-1.05.87l-.91-.38c-.2-.08-.39-.04-.56.15a.42.42 0 0 0-.04.54l.54.85c-.27.37-.48.76-.68 1.19l-1-.05a.44.44 0 0 0-.46.32c-.08.21-.02.4.16.52l.78.62c-.11.44-.2.88-.23 1.35l-.95.3C.61 9.62.5 9.76.5 10s.11.38.33.46l.95.3c.03.47.11.92.23 1.35l-.78.61c-.18.13-.23.33-.16.54.07.22.24.33.46.31l1-.05c.2.42.41.82.67 1.19l-.53.85c-.12.19-.1.39.04.55.17.19.36.23.56.14l.91-.38c.32.33.68.62 1.05.87l-.2.98c-.04.23.02.4.21.52.22.1.4.08.57-.08l.73-.65c.41.18.84.35 1.28.47l.14.98c.03.23.17.37.39.41.23.03.4-.06.5-.25l.46-.89a6.96 6.96 0 0 0 1.32 0Zm1.46-8.74c-.35-1.04-1.15-1.64-2.1-1.64-.17 0-.35.02-.6.1L6.86 3.62a7 7 0 0 1 10.11 5.86h-4.9ZM5.95 4.18A7.08 7.08 0 0 0 3.01 10a7.1 7.1 0 0 0 2.91 5.8l2.58-4.24c-.47-.47-.7-.97-.7-1.53s.24-1.08.69-1.53L5.95 4.18Zm2.95 5.85c0-.6.5-1.08 1.09-1.08.6 0 1.1.47 1.1 1.08 0 .6-.5 1.09-1.1 1.09a1.1 1.1 0 0 1-1.09-1.1Zm-2.07 6.32c.94.47 2.02.74 3.17.74a6.97 6.97 0 0 0 6.98-6.57h-4.9c-.33 1.06-1.12 1.7-2.1 1.7-.16 0-.34-.03-.59-.09l-2.56 4.22Z"/></svg></span>`,
};

const escapeGuideText = (value: string) => value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]!));

const guideKeyword = (label: string, icon = "") => `<span class="guide-keyword">${escapeGuideText(label)}${icon}</span>`;

const renderGuidePattern = (pattern: string, replacements: Record<string, string>) => {
  let value = escapeGuideText(pattern);
  for (const [placeholder, replacement] of Object.entries(replacements)) value = value.split(placeholder).join(replacement);
  return value;
};

class AppLaunchActions extends HTMLElement {
  private root = this.attachShadow({ mode: "open" });
  connectedCallback() {
    const copy = functionalCopy();
    const android = /Android/i.test(navigator.userAgent);
    const ios = /iPhone|iPad|iPod/i.test(navigator.userAgent);
    const config = runtimeConfig();
    const simulatedDevice = config.previewMode ? config.previewDevice : undefined;
    const mobile = simulatedDevice
      ? simulatedDevice === "mobile" || simulatedDevice === "tablet"
      : android || ios;
    const openInstruction = renderGuidePattern(copy.instructionOpenPattern, { "{=m2}": guideKeyword(copy.whatsappLabel, appGuideIcons.whatsapp) });
    const platformInstruction = renderGuidePattern(copy.instructionPlatformPattern, { "{=m1}": guideKeyword(copy.menuLabel, appGuideIcons.menu), "{=m5}": guideKeyword(copy.settingsLabel, appGuideIcons.settings) });
    const linkedInstruction = renderGuidePattern(copy.instructionLinkedPattern, { "{=m1}": guideKeyword(copy.linkedDevicesLabel), "{=m3}": guideKeyword(copy.linkDeviceLabel) });
    const enterInstruction = renderGuidePattern(copy.instructionEnterPattern, { "{=m1}": guideKeyword(copy.phoneLinkLabel) });
    this.root.innerHTML = `<style>${sharedStyle}
      :host{display:block}.actions{display:flex;gap:.65rem;flex-wrap:wrap}button{min-height:2.75rem;padding:.6rem .9rem;border:1px solid currentColor;border-radius:var(--account-link-secondary-radius,.65rem);background:transparent}
      .guide{margin:.85rem 0 0}.steps{display:grid;gap:.65rem;margin:0;padding-inline-start:1.65rem;font-size:.9rem;line-height:1.55}.steps li{padding-inline-start:.25rem}.guide-keyword{display:inline-flex;align-items:center;gap:.3rem;flex-wrap:nowrap;font-weight:600;vertical-align:middle}.guide-icon{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;vertical-align:middle;color:#667085}.guide-icon svg{display:block}.whatsapp-icon svg{width:1.75rem;height:1.75rem}.menu-icon,.settings-icon{width:1.65rem;height:1.85rem;padding:.16rem;border:1px solid #929292;border-radius:.45rem;background:#f4f4f4}.menu-icon svg{width:1.05rem;height:1.05rem}.settings-icon svg{width:1.15rem;height:1.15rem}.fallback{margin:.65rem 0 0;color:var(--account-link-warning,#92400e);font-size:.9rem}
    </style><section part="panel"><div class="actions" part="actions" ${mobile ? "" : "hidden"}><button part="consumer-button" data-app="consumer" type="button">${copy.openConsumer}</button><button part="business-button" data-app="business" type="button">${copy.openBusiness}</button></div><div class="guide" part="guide"><ol class="steps" part="guide-steps"><li>${openInstruction}</li><li>${platformInstruction}</li><li>${linkedInstruction}</li><li>${enterInstruction}</li></ol></div><p class="fallback" part="fallback" hidden>${copy.appFallback}</p></section>`;
    this.root.querySelectorAll<HTMLButtonElement>("button[data-app]").forEach((button) => button.addEventListener("click", () => this.launch(button.dataset.app === "business" ? "business" : "consumer")));
  }
  private launch(app: "consumer" | "business") {
    const fallback = this.root.querySelector<HTMLElement>(".fallback")!;
    fallback.hidden = true;
    let pageHidden = false;
    const onVisibility = () => { if (document.visibilityState === "hidden") pageHidden = true; };
    document.addEventListener("visibilitychange", onVisibility, { once: true });
    this.dispatchEvent(new CustomEvent("account-link-app-launch", { bubbles: true, detail: { app, status: "attempted" } }));
    window.location.href = app === "business" ? "whatsapp-business://" : "whatsapp://";
    window.setTimeout(() => {
      if (!pageHidden && document.visibilityState === "visible") {
        fallback.hidden = false;
        this.dispatchEvent(new CustomEvent("account-link-app-launch", { bubbles: true, detail: { app, status: "fallback_shown" } }));
      }
    }, 1200);
  }
}

class AccountLinkStatus extends HTMLElement {
  private root = this.attachShadow({ mode: "open" });
  connectedCallback() {
    this.root.innerHTML = `<style>${sharedStyle}:host{display:block}.status{margin:0;min-height:1.5em}.error{color:var(--account-link-error,#b91c1c)}.success{color:var(--account-link-success,#047857)}button{margin-top:.75rem;min-height:2.75rem;padding:.6rem .9rem;border:1px solid currentColor;border-radius:var(--account-link-secondary-radius,.65rem);background:transparent}</style><div part="panel"><p class="status" part="message" role="status" aria-live="polite"></p><button part="retry-button" type="button" hidden>${functionalCopy().retry}</button></div>`;
    this.root.querySelector("button")!.addEventListener("click", () => this.dispatchEvent(new CustomEvent("account-link-retry", { bubbles: true })));
  }
  setState(state: string, message?: string) {
    const copy = functionalCopy();
    const messages: Record<string, string> = { waiting_phone: copy.waiting, code_issued: copy.waiting, reconnecting: copy.reconnecting, verified: copy.verified, expired: copy.expired, failed: copy.failed, cancelled: copy.cancelled, account_already_linked: copy.alreadyLinked, number_unavailable: copy.unavailable, pairing_in_progress: copy.inProgress };
    const node = this.root.querySelector<HTMLElement>(".status")!;
    node.textContent = message || messages[state] || copy.failed;
    node.className = `status ${state === "verified" ? "success" : ["expired", "failed", "cancelled", "account_already_linked", "number_unavailable", "pairing_in_progress"].includes(state) ? "error" : ""}`;
    const retry = this.root.querySelector<HTMLButtonElement>("button")!;
    retry.hidden = !["expired", "failed", "cancelled", "account_already_linked", "number_unavailable", "pairing_in_progress"].includes(state);
    this.hidden = false;
  }
  reset() { this.hidden = true; }
}

class AccountInitializationStatus extends HTMLElement {
  private root = this.attachShadow({ mode: "open" });
  connectedCallback() { this.root.innerHTML = `<style>${sharedStyle}:host{display:block}.status{margin:0;color:var(--account-link-muted,#475569)}</style><p class="status" part="message" role="status" aria-live="polite"></p>`; }
  setState(state: string) {
    const copy = functionalCopy();
    this.root.querySelector("p")!.textContent = state === "ready" ? copy.initialized : ["failed", "unsupported", "partial"].includes(state) ? copy.initializationPartial : copy.initializing;
    this.hidden = false;
  }
  reset() { this.hidden = true; }
}

class AccountLinkFlow extends HTMLElement {
  private pairing?: PairingHandle;
  private pollTimer?: number;
  private pollFailures = 0;
  private phone!: PhoneNumberField;
  private submit!: AccountLinkSubmit;
  private code!: PairingCodePanel;
  private apps!: AppLaunchActions;
  private status!: AccountLinkStatus;
  private initialization?: AccountInitializationStatus;
  private previewStateChanged = (event: Event) => {
    if (!this.pairing) return;
    const data = (event as CustomEvent<Record<string, unknown>>).detail;
    if (data) this.applyPairingState(data, false);
  };

  connectedCallback() {
    this.phone = this.querySelector("phone-number-field") as PhoneNumberField;
    this.submit = this.querySelector("account-link-submit") as AccountLinkSubmit;
    this.code = this.querySelector("pairing-code-panel") as PairingCodePanel;
    this.apps = this.querySelector("app-launch-actions") as AppLaunchActions;
    this.status = this.querySelector("account-link-status") as AccountLinkStatus;
    this.initialization = this.querySelector("account-initialization-status") as AccountInitializationStatus | undefined;
    if (!this.phone || !this.submit || !this.code || !this.apps || !this.status) throw new Error("account-link-flow requires the standard account-link elements");
    this.code.hidden = true; this.apps.hidden = true; this.status.hidden = true; if (this.initialization) this.initialization.hidden = true;
    this.addEventListener("account-link-submit", () => void this.start());
    this.addEventListener("account-link-retry", () => void this.reset());
    window.addEventListener("promotion-preview-state-change", this.previewStateChanged);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && this.pairing) void this.poll(); });
  }

  disconnectedCallback() {
    window.removeEventListener("promotion-preview-state-change", this.previewStateChanged);
    if (this.pollTimer) clearTimeout(this.pollTimer);
  }

  private async start() {
    const phone = this.phone.getPhone();
    if (!phone) { this.phone.setError(functionalCopy().invalidPhone); return; }
    const bridge = (window as unknown as { PromotionBridge?: { submitPhone(phone: string, metadata?: Record<string, unknown>): Promise<Response> } }).PromotionBridge;
    if (!bridge?.submitPhone) { this.status.setState("failed"); return; }
    this.submit.setLoading(true);
    try {
      const response = await bridge.submitPhone(phone.e164, { componentKit: "account-link-elements/v1", locale: resolvedLocale(), countrySource: "browser" });
      const payload = await response.json();
      const pairing = payload?.data?.pairing as PairingHandle | undefined;
      if (!pairing?.pairingCode) throw Object.assign(new Error("pairing code missing"), { code: "pairing_start_failed" });
      this.pairing = pairing;
      this.dispatchEvent(new CustomEvent("account-link-pairing-started", { bubbles: true, detail: { attemptId: pairing.attemptId } }));
      this.phone.hidden = true; this.submit.hidden = true;
      this.code.show(pairing); this.apps.hidden = false; this.status.setState(pairing.pairingStatus || "waiting_phone");
      this.pollFailures = 0;
      void this.poll();
    } catch (error) {
      const value = error as BridgeError;
      const code = value.code || "failed";
      if (code === "invalid_phone") {
        this.phone.setError(functionalCopy().invalidPhone);
        this.status.reset();
      } else if (
        [
          "account_already_linked",
          "number_unavailable",
          "pairing_in_progress",
        ].includes(code)
      ) {
        this.status.setState(code);
      } else {
        // Operational details remain in the management console. Visitors only
        // need a concise retryable failure state.
        this.status.setState("failed");
      }
    } finally { this.submit.setLoading(false); }
  }

  private schedule(delay: number) { if (this.pollTimer) clearTimeout(this.pollTimer); this.pollTimer = window.setTimeout(() => void this.poll(), delay); }

  private applyPairingState(data: Record<string, unknown>, scheduleNext: boolean) {
    const state = String(data.pairingStatus || "failed");
    this.pollFailures = 0;
    if (data.verified === true && state === "verified") {
      this.status.setState("verified"); this.code.reset(); this.apps.hidden = true;
      if (this.initialization) this.initialization.setState(String(data.initializationStatus || "pending"));
      if (scheduleNext && ["pending", "syncing"].includes(String(data.initializationStatus || "pending"))) {
        this.schedule(Number(data.nextPollAfterMs) || 2000);
      }
      return;
    }
    if (this.pairing && this.code.hidden) this.code.show(this.pairing);
    this.apps.hidden = false;
    this.initialization?.reset();
    this.status.setState(state);
    if (["failed", "expired", "cancelled"].includes(state)) return;
    if (scheduleNext) this.schedule(Number(data.nextPollAfterMs) || 2000);
  }

  private async poll() {
    if (!this.pairing || document.visibilityState === "hidden") return;
    const bridge = (window as unknown as { PromotionBridge?: { getPairingStatus(pairing: PairingHandle): Promise<Response> } }).PromotionBridge;
    if (!bridge?.getPairingStatus) { this.status.setState("failed"); return; }
    try {
      const response = await bridge.getPairingStatus(this.pairing);
      if (response.status === 429) {
        const retryAfterSeconds = Number(response.headers.get("Retry-After"));
        this.pollFailures = 0;
        this.schedule(
          Number.isFinite(retryAfterSeconds) && retryAfterSeconds > 0
            ? retryAfterSeconds * 1000
            : 5000,
        );
        return;
      }
      if (!response.ok) throw new Error("status rejected");
      const payload = await response.json();
      this.applyPairingState(payload?.data || {}, true);
    } catch {
      this.pollFailures += 1;
      this.schedule(Math.min(2000 * (2 ** Math.min(this.pollFailures, 3)), 15000));
    }
  }

  private async reset() {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    const pairing = this.pairing; this.pairing = undefined;
    const bridge = (window as unknown as { PromotionBridge?: { cancelPairing(pairing: PairingHandle): Promise<Response> } }).PromotionBridge;
    if (pairing && bridge?.cancelPairing) { try { await bridge.cancelPairing(pairing); } catch { /* terminal attempts are safe to leave */ } }
    this.code.reset(); this.apps.hidden = true; this.status.reset(); this.initialization?.reset(); this.phone.reset(); this.phone.hidden = false; this.submit.hidden = false;
    this.dispatchEvent(new CustomEvent("account-link-reset", { bubbles: true }));
  }
}

customElements.define("account-link-locale-switcher", AccountLinkLocaleSwitcher);
customElements.define("phone-number-field", PhoneNumberField);
customElements.define("account-link-submit", AccountLinkSubmit);
customElements.define("pairing-code-panel", PairingCodePanel);
customElements.define("app-launch-actions", AppLaunchActions);
customElements.define("account-link-status", AccountLinkStatus);
customElements.define("account-initialization-status", AccountInitializationStatus);
customElements.define("account-link-flow", AccountLinkFlow);

declare global {
  interface Window { AccountLinkElements?: { version: string; browserCountry(): CountryCode | undefined } }
}

window.AccountLinkElements = { version: "account-link-elements/v1", browserCountry };
