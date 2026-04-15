"""
Multilingual translation module for the dental chatbot.
Supports: English (en), Arabic (ar), Urdu (ur), Tagalog (tl)
"""

from langdetect import detect, LangDetectException

SUPPORTED_LANGUAGES = {'en', 'ar', 'ur', 'tl'}  # English, Arabic, Urdu, Tagalog
LANGUAGE_NAMES = {
    'en': 'English',
    'ar': 'العربية',
    'ur': 'اردو',
    'tl': 'Tagalog'
}


def detect_language(text):
    """Detect language from text. Returns language code or 'en' as fallback."""
    try:
        lang = detect(text)
        # Map language codes (langdetect uses ISO 639-1)
        if lang in SUPPORTED_LANGUAGES:
            return lang
        # Some mappings
        if lang == 'fil':  # Filipino/Tagalog
            return 'tl'
        return 'en'  # Unsupported → fallback to English
    except LangDetectException:
        return 'en'


# ---------------------------------------------------------------------------
# Complete translation dictionary
# ---------------------------------------------------------------------------

TRANSLATIONS = {

    # ── Booking flow ──────────────────────────────────────────────────────

    'greeting': {
        'en': "Hi! I'm your dental assistant. How can I help you today?",
        'ar': "مرحباً! أنا مساعدك لطب الأسنان. كيف يمكنني مساعدتك اليوم؟",
        'ur': "ہیلو! میں آپ کا ڈینٹل اسسٹنٹ ہوں۔ آج میں آپ کی کیسے مدد کر سکتا ہوں؟",
        'tl': "Kumusta! Ako ang iyong dental assistant. Paano kita matutulungan ngayon?"
    },

    'ask_name': {
        'en': "To get started, what's your name?",
        'ar': "للبدء، ما اسمك؟",
        'ur': "شروع کرنے کے لیے، آپ کا نام کیا ہے؟",
        'tl': "Para makapagsimula, ano ang pangalan mo?"
    },

    'nice_to_meet': {
        'en': "Nice to meet you, {name}! What type of doctor would you like to see?",
        'ar': "تشرفنا بك يا {name}! ما التخصص الذي تودّ حجز موعد فيه؟",
        'ur': "آپ سے مل کر خوشی ہوئی، {name}! آپ کس قسم کے ڈاکٹر سے ملنا چاہیں گے؟",
        'tl': "Ikinagagalak kitang makilala, {name}! Anong uri ng doktor ang gusto mong puntahan?"
    },

    'ask_category': {
        'en': "What type of doctor would you like to see?",
        'ar': "ما التخصص الذي تودّ حجز موعد فيه؟",
        'ur': "آپ کس قسم کے ڈاکٹر سے ملنا چاہیں گے؟",
        'tl': "Anong uri ng doktor ang gusto mong puntahan?"
    },

    'invalid_category': {
        'en': "I didn't recognize that specialty. Please pick one from the list:",
        'ar': "لم أتعرّف على هذا التخصص. يرجى اختيار تخصص من القائمة:",
        'ur': "مجھے یہ تخصص سمجھ نہیں آیا۔ براہ کرم فہرست میں سے ایک منتخب کریں:",
        'tl': "Hindi ko nakilala ang espesyalidad na iyon. Pumili mula sa listahan:"
    },

    'ask_doctor': {
        'en': "Which doctor would you like to see?",
        'ar': "أيّ طبيب تودّ زيارته؟",
        'ur': "آپ کس ڈاکٹر سے ملنا چاہیں گے؟",
        'tl': "Aling doktor ang gusto mong puntahan?"
    },

    'invalid_doctor': {
        'en': "I didn't recognize that doctor. Please pick one from the list:",
        'ar': "لم أتعرّف على هذا الطبيب. يرجى اختيار طبيب من القائمة:",
        'ur': "مجھے یہ ڈاکٹر سمجھ نہیں آیا۔ براہ کرم فہرست میں سے ایک منتخب کریں:",
        'tl': "Hindi ko nakilala ang doktor na iyon. Pumili mula sa listahan:"
    },

    'doctor_selected': {
        'en': "Great choice! You'll be seeing Dr. {doctor}. When would you like to come in?",
        'ar': "اختيار ممتاز! ستكون زيارتك لدى د. {doctor}. متى تودّ الحضور؟",
        'ur': "بہترین انتخاب! آپ ڈاکٹر {doctor} سے ملیں گے۔ آپ کب آنا چاہیں گے؟",
        'tl': "Magandang pagpili! Makikita mo si Dr. {doctor}. Kailan mo gustong pumunta?"
    },

    'ask_date': {
        'en': "When would you like to come in?",
        'ar': "متى تودّ الحضور؟",
        'ur': "آپ کب آنا چاہیں گے؟",
        'tl': "Kailan mo gustong pumunta?"
    },

    'invalid_date': {
        'en': "I couldn't understand that date. Please select a date from the calendar:",
        'ar': "لم أتمكّن من فهم التاريخ. يرجى اختيار تاريخ من التقويم:",
        'ur': "مجھے یہ تاریخ سمجھ نہیں آئی۔ براہ کرم کیلنڈر سے تاریخ منتخب کریں:",
        'tl': "Hindi ko naintindihan ang petsang iyon. Pumili ng petsa mula sa kalendaryo:"
    },

    'weekend_closed': {
        'en': "We're closed on weekends. Please pick a weekday:",
        'ar': "العيادة مغلقة في عطلة نهاية الأسبوع. يرجى اختيار يوم عمل:",
        'ur': "ہم ہفتے کے آخر میں بند رہتے ہیں۔ براہ کرم کوئی ورکنگ ڈے منتخب کریں:",
        'tl': "Sarado kami tuwing weekend. Pumili ng weekday:"
    },

    'ask_time': {
        'en': "What time works best for you?",
        'ar': "ما الوقت الأنسب لك؟",
        'ur': "آپ کے لیے کون سا وقت مناسب ہے؟",
        'tl': "Anong oras ang pinakamaginhawa para sa iyo?"
    },

    'invalid_time': {
        'en': "I didn't catch that time. Please pick from the available slots:",
        'ar': "لم أتمكّن من تحديد الوقت. يرجى الاختيار من المواعيد المتاحة:",
        'ur': "مجھے وقت سمجھ نہیں آیا۔ براہ کرم دستیاب اوقات میں سے منتخب کریں:",
        'tl': "Hindi ko nakuha ang oras na iyon. Pumili mula sa mga available na slot:"
    },

    'ask_email': {
        'en': "What's your email address? We'll send you a confirmation.",
        'ar': "ما عنوان بريدك الإلكتروني؟ سنرسل لك تأكيداً بالحجز.",
        'ur': "آپ کا ای میل ایڈریس کیا ہے؟ ہم آپ کو تصدیق بھیجیں گے۔",
        'tl': "Ano ang iyong email address? Magpapadala kami ng kumpirmasyon."
    },

    'invalid_email': {
        'en': "That doesn't look like a valid email. Please try again:",
        'ar': "يبدو أن البريد الإلكتروني غير صحيح. يرجى المحاولة مرة أخرى:",
        'ur': "یہ درست ای میل نہیں لگتا۔ براہ کرم دوبارہ کوشش کریں:",
        'tl': "Mukhang hindi valid ang email na iyon. Pakisubukan ulit:"
    },

    'ask_phone': {
        'en': "What's your phone number?",
        'ar': "ما رقم هاتفك؟",
        'ur': "آپ کا فون نمبر کیا ہے؟",
        'tl': "Ano ang numero ng telepono mo?"
    },

    'invalid_phone': {
        'en': "That doesn't look like a valid phone number. Please try again:",
        'ar': "يبدو أن رقم الهاتف غير صحيح. يرجى المحاولة مرة أخرى:",
        'ur': "یہ درست فون نمبر نہیں لگتا۔ براہ کرم دوبارہ کوشش کریں:",
        'tl': "Mukhang hindi valid ang numero ng telepono. Pakisubukan ulit:"
    },

    # ── Booking confirmation ──────────────────────────────────────────────

    'booking_confirmed': {
        'en': "Your appointment is confirmed! Here are the details:",
        'ar': "تم تأكيد موعدك! إليك التفاصيل:",
        'ur': "آپ کی اپائنٹمنٹ کی تصدیق ہو گئی! یہ رہی تفصیلات:",
        'tl': "Nakumpirma na ang iyong appointment! Narito ang mga detalye:"
    },

    'booking_date': {
        'en': "Date: {date}",
        'ar': "التاريخ: {date}",
        'ur': "تاریخ: {date}",
        'tl': "Petsa: {date}"
    },

    'booking_time': {
        'en': "Time: {time}",
        'ar': "الوقت: {time}",
        'ur': "وقت: {time}",
        'tl': "Oras: {time}"
    },

    'booking_doctor': {
        'en': "Doctor: Dr. {doctor}",
        'ar': "الطبيب: د. {doctor}",
        'ur': "ڈاکٹر: ڈاکٹر {doctor}",
        'tl': "Doktor: Dr. {doctor}"
    },

    'confirmation_email_sent': {
        'en': "A confirmation email has been sent to {email}.",
        'ar': "تم إرسال بريد تأكيد إلى {email}.",
        'ur': "{email} پر تصدیقی ای میل بھیج دی گئی ہے۔",
        'tl': "Naipadala na ang confirmation email sa {email}."
    },

    'previsit_form_sent': {
        'en': "We've also sent you a pre-visit form to fill out before your appointment.",
        'ar': "أرسلنا لك أيضاً نموذج ما قبل الزيارة لملئه قبل موعدك.",
        'ur': "ہم نے آپ کو اپائنٹمنٹ سے پہلے پُر کرنے کے لیے ایک پری وزٹ فارم بھی بھیجا ہے۔",
        'tl': "Nagpadala rin kami ng pre-visit form na dapat mong sagutan bago ang iyong appointment."
    },

    'anything_else': {
        'en': "Is there anything else I can help you with?",
        'ar': "هل هناك أي شيء آخر يمكنني مساعدتك فيه؟",
        'ur': "کیا کوئی اور چیز ہے جس میں میں آپ کی مدد کر سکتا ہوں؟",
        'tl': "May iba pa ba akong maitutulong sa iyo?"
    },

    # ── Waitlist ──────────────────────────────────────────────────────────

    'slot_booked': {
        'en': "This slot is fully booked. Would you like to join the waitlist? We'll notify you immediately if a spot opens.",
        'ar': "هذا الموعد محجوز بالكامل. هل تودّ الانضمام إلى قائمة الانتظار؟ سنُعلمك فوراً عند توفّر مكان.",
        'ur': "یہ سلاٹ مکمل طور پر بک ہے۔ کیا آپ ویٹ لسٹ میں شامل ہونا چاہیں گے؟ جگہ خالی ہونے پر ہم آپ کو فوراً مطلع کریں گے۔",
        'tl': "Puno na ang slot na ito. Gusto mo bang sumali sa waitlist? Aabisuhan ka namin kaagad kapag may nagbukas na puwesto."
    },

    'waitlist_joined': {
        'en': "You've been added to the waitlist at position {position}. We'll notify you as soon as a spot opens!",
        'ar': "تمت إضافتك إلى قائمة الانتظار في المركز {position}. سنُعلمك فور توفّر مكان!",
        'ur': "آپ کو ویٹ لسٹ میں پوزیشن {position} پر شامل کر لیا گیا ہے۔ جگہ خالی ہوتے ہی ہم آپ کو مطلع کریں گے!",
        'tl': "Naidagdag ka na sa waitlist sa posisyon {position}. Aabisuhan ka namin pagkakaroon ng bakante!"
    },

    'waitlist_slot_available': {
        'en': "Great news! A spot opened with Dr. {doctor} on {date} at {time}. You have {deadline} to confirm.",
        'ar': "أخبار سارّة! تتوفّر الآن فرصة مع د. {doctor} بتاريخ {date} الساعة {time}. لديك {deadline} للتأكيد.",
        'ur': "خوشخبری! ڈاکٹر {doctor} کے پاس {date} کو {time} بجے جگہ خالی ہوئی ہے۔ تصدیق کے لیے آپ کے پاس {deadline} ہے۔",
        'tl': "Magandang balita! May bakante kay Dr. {doctor} sa {date} ng {time}. Mayroon kang {deadline} para kumpirmahin."
    },

    'waitlist_expired': {
        'en': "Your waitlist spot has expired. Would you like to join the waitlist for another slot?",
        'ar': "انتهت صلاحية مكانك في قائمة الانتظار. هل تودّ الانضمام لقائمة انتظار موعد آخر؟",
        'ur': "آپ کی ویٹ لسٹ کی جگہ ختم ہو گئی ہے۔ کیا آپ کسی اور سلاٹ کی ویٹ لسٹ میں شامل ہونا چاہیں گے؟",
        'tl': "Nag-expire na ang iyong puwesto sa waitlist. Gusto mo bang sumali sa waitlist para sa ibang slot?"
    },

    # ── Emergency ─────────────────────────────────────────────────────────

    'emergency_detected': {
        'en': "This sounds like an emergency. Here's what to do right now:",
        'ar': "يبدو أن هذه حالة طارئة. إليك ما يجب فعله الآن:",
        'ur': "یہ ایک ایمرجنسی لگتی ہے۔ ابھی یہ کریں:",
        'tl': "Mukhang emergency ito. Narito ang dapat mong gawin ngayon:"
    },

    'emergency_slot_check': {
        'en': "Let me check our next available emergency slot...",
        'ar': "دعني أتحقّق من أقرب موعد طوارئ متاح...",
        'ur': "مجھے اگلا دستیاب ایمرجنسی سلاٹ چیک کرنے دیں...",
        'tl': "Hayaan mong tingnan ko ang susunod na available na emergency slot..."
    },

    'emergency_no_slots': {
        'en': "We have no emergency slots available right now. Please call us directly or go to the nearest emergency dental clinic.",
        'ar': "لا تتوفّر مواعيد طوارئ حالياً. يرجى الاتصال بنا مباشرة أو التوجّه لأقرب عيادة أسنان طوارئ.",
        'ur': "اس وقت کوئی ایمرجنسی سلاٹ دستیاب نہیں ہے۔ براہ کرم ہمیں براہ راست کال کریں یا قریب ترین ایمرجنسی ڈینٹل کلینک جائیں۔",
        'tl': "Wala kaming available na emergency slot ngayon. Tumawag sa amin nang direkta o pumunta sa pinakamalapit na emergency dental clinic."
    },

    'emergency_call': {
        'en': "Prefer to call us directly?",
        'ar': "هل تفضّل الاتصال بنا مباشرة؟",
        'ur': "کیا آپ ہمیں براہ راست کال کرنا چاہیں گے؟",
        'tl': "Mas gusto mo bang tumawag sa amin nang direkta?"
    },

    # ── General ───────────────────────────────────────────────────────────

    'welcome_back': {
        'en': "Welcome back, {name}! Great to hear from you again. How can I help?",
        'ar': "أهلاً بعودتك يا {name}! سعيدون بتواصلك مجدداً. كيف يمكنني مساعدتك؟",
        'ur': "خوش آمدید واپس، {name}! آپ سے دوبارہ بات کر کے خوشی ہوئی۔ میں کیسے مدد کر سکتا ہوں؟",
        'tl': "Maligayang pagbabalik, {name}! Natutuwa akong marinig ka ulit. Paano kita matutulungan?"
    },

    'language_unsupported': {
        'en': "I'll respond in English as I don't support your language yet.",
        'ar': "سأجيب بالإنجليزية لأن لغتك غير مدعومة حالياً.",
        'ur': "میں انگریزی میں جواب دوں گا کیونکہ آپ کی زبان ابھی تک معاون نہیں ہے۔",
        'tl': "Sasagot ako sa Ingles dahil hindi ko pa sinusuportahan ang iyong wika."
    },

    'cancel_confirm': {
        'en': "Your appointment has been cancelled successfully.",
        'ar': "تم إلغاء موعدك بنجاح.",
        'ur': "آپ کی اپائنٹمنٹ کامیابی سے منسوخ ہو گئی ہے۔",
        'tl': "Matagumpay na nakansela ang iyong appointment."
    },

    'error_generic': {
        'en': "Sorry, something went wrong. Please try again.",
        'ar': "عذراً، حدث خطأ ما. يرجى المحاولة مرة أخرى.",
        'ur': "معذرت، کچھ غلط ہو گیا۔ براہ کرم دوبارہ کوشش کریں۔",
        'tl': "Paumanhin, may nangyaring mali. Pakisubukan ulit."
    },

    'goodbye': {
        'en': "Thank you for visiting! Have a wonderful day.",
        'ar': "شكراً لزيارتك! أتمنى لك يوماً سعيداً.",
        'ur': "آنے کا شکریہ! آپ کا دن اچھا گزرے۔",
        'tl': "Salamat sa pagbisita! Magandang araw sa iyo."
    },

    'handoff_connecting': {
        'en': "Let me connect you with one of our team members who can help you better.",
        'ar': "دعني أوصلك بأحد أعضاء فريقنا ليساعدك بشكل أفضل.",
        'ur': "مجھے آپ کو ہماری ٹیم کے ایک رکن سے جوڑنے دیں جو آپ کی بہتر مدد کر سکتا ہے۔",
        'tl': "Ikokonekta kita sa isa sa aming team na mas makakatulong sa iyo."
    },

    'handoff_connected': {
        'en': "You are now connected with {staff} from our team.",
        'ar': "أنت الآن متصل بـ {staff} من فريقنا.",
        'ur': "آپ اب ہماری ٹیم سے {staff} کے ساتھ جڑے ہوئے ہیں۔",
        'tl': "Nakakonekta ka na kay {staff} mula sa aming team."
    },

    'handoff_busy': {
        'en': "Our team is currently busy. We will message you back within 1 hour.",
        'ar': "فريقنا مشغول حالياً. سنراسلك خلال ساعة واحدة.",
        'ur': "ہماری ٹیم اس وقت مصروف ہے۔ ہم ایک گھنٹے کے اندر آپ کو پیغام بھیجیں گے۔",
        'tl': "Abala ang aming team sa ngayon. Magme-message kami sa iyo sa loob ng 1 oras."
    },

    'loyalty_balance': {
        'en': "You currently have {points} loyalty points worth {value} {currency}.",
        'ar': "لديك حالياً {points} نقطة ولاء بقيمة {value} {currency}.",
        'ur': "آپ کے پاس اس وقت {points} لائلٹی پوائنٹس ہیں جن کی مالیت {value} {currency} ہے۔",
        'tl': "Mayroon kang {points} loyalty points na nagkakahalaga ng {value} {currency}."
    },

    'discount_applied': {
        'en': "Code applied! Your total is {new_total} {currency} instead of {original} {currency} ({percent}% off).",
        'ar': "تم تطبيق الكود! إجمالي المبلغ {new_total} {currency} بدلاً من {original} {currency} (خصم {percent}%).",
        'ur': "کوڈ لاگو ہو گیا! آپ کی کل رقم {original} {currency} کے بجائے {new_total} {currency} ہے ({percent}% چھوٹ)۔",
        'tl': "Na-apply na ang code! Ang total mo ay {new_total} {currency} sa halip na {original} {currency} ({percent}% off)."
    },

    'discount_invalid': {
        'en': "This code is not valid. Please check and try again.",
        'ar': "هذا الكود غير صالح. يرجى التحقق والمحاولة مرة أخرى.",
        'ur': "یہ کوڈ درست نہیں ہے۔ براہ کرم چیک کریں اور دوبارہ کوشش کریں۔",
        'tl': "Hindi valid ang code na ito. Pakitingnan at subukan ulit."
    },

    'discount_expired': {
        'en': "This code expired on {date}.",
        'ar': "انتهت صلاحية هذا الكود بتاريخ {date}.",
        'ur': "اس کوڈ کی میعاد {date} کو ختم ہو گئی۔",
        'tl': "Nag-expire ang code na ito noong {date}."
    },

    # ── Pre-visit form labels ─────────────────────────────────────────────

    'form_title': {
        'en': "Pre-Visit Medical Form",
        'ar': "نموذج المعلومات الطبية قبل الزيارة",
        'ur': "پری وزٹ میڈیکل فارم",
        'tl': "Pre-Visit Medical Form"
    },

    'form_personal': {
        'en': "Personal Information",
        'ar': "المعلومات الشخصية",
        'ur': "ذاتی معلومات",
        'tl': "Personal na Impormasyon"
    },

    'form_name': {
        'en': "Full Name",
        'ar': "الاسم الكامل",
        'ur': "پورا نام",
        'tl': "Buong Pangalan"
    },

    'form_dob': {
        'en': "Date of Birth",
        'ar': "تاريخ الميلاد",
        'ur': "تاریخ پیدائش",
        'tl': "Petsa ng Kapanganakan"
    },

    'form_gender': {
        'en': "Gender",
        'ar': "الجنس",
        'ur': "جنس",
        'tl': "Kasarian"
    },

    'form_male': {
        'en': "Male",
        'ar': "ذكر",
        'ur': "مرد",
        'tl': "Lalaki"
    },

    'form_female': {
        'en': "Female",
        'ar': "أنثى",
        'ur': "عورت",
        'tl': "Babae"
    },

    'form_other': {
        'en': "Other",
        'ar': "آخر",
        'ur': "دیگر",
        'tl': "Iba pa"
    },

    'form_medical_history': {
        'en': "Medical History",
        'ar': "التاريخ الطبي",
        'ur': "طبی تاریخ",
        'tl': "Kasaysayang Medikal"
    },

    'form_diabetes': {
        'en': "Diabetes",
        'ar': "السكري",
        'ur': "ذیابیطس",
        'tl': "Diabetes"
    },

    'form_hypertension': {
        'en': "Hypertension",
        'ar': "ارتفاع ضغط الدم",
        'ur': "ہائی بلڈ پریشر",
        'tl': "Hypertension"
    },

    'form_heart_disease': {
        'en': "Heart Disease",
        'ar': "أمراض القلب",
        'ur': "دل کی بیماری",
        'tl': "Sakit sa Puso"
    },

    'form_blood_thinners': {
        'en': "Blood Thinners",
        'ar': "أدوية سيولة الدم",
        'ur': "خون پتلا کرنے والی ادویات",
        'tl': "Blood Thinners"
    },

    'form_allergies_check': {
        'en': "Allergies",
        'ar': "حساسية",
        'ur': "الرجی",
        'tl': "Mga Allergy"
    },

    'form_pregnancy': {
        'en': "Pregnancy",
        'ar': "حمل",
        'ur': "حمل",
        'tl': "Pagbubuntis"
    },

    'form_asthma': {
        'en': "Asthma",
        'ar': "الربو",
        'ur': "دمہ",
        'tl': "Hika"
    },

    'form_other_condition': {
        'en': "Other (please specify)",
        'ar': "أخرى (يرجى التحديد)",
        'ur': "دیگر (براہ کرم وضاحت کریں)",
        'tl': "Iba pa (pakitukoy)"
    },

    'form_medications': {
        'en': "Current Medications",
        'ar': "الأدوية الحالية",
        'ur': "موجودہ ادویات",
        'tl': "Kasalukuyang Gamot"
    },

    'form_allergies': {
        'en': "Known Allergies",
        'ar': "أنواع الحساسية المعروفة",
        'ur': "معلوم الرجیاں",
        'tl': "Mga Kilalang Allergy"
    },

    'form_insurance': {
        'en': "Insurance (Optional)",
        'ar': "التأمين (اختياري)",
        'ur': "انشورنس (اختیاری)",
        'tl': "Insurance (Opsyonal)"
    },

    'form_insurance_provider': {
        'en': "Insurance Provider",
        'ar': "شركة التأمين",
        'ur': "انشورنس فراہم کنندہ",
        'tl': "Insurance Provider"
    },

    'form_policy_number': {
        'en': "Policy Number",
        'ar': "رقم الوثيقة",
        'ur': "پالیسی نمبر",
        'tl': "Policy Number"
    },

    'form_signature': {
        'en': "Digital Signature",
        'ar': "التوقيع الرقمي",
        'ur': "ڈیجیٹل دستخط",
        'tl': "Digital na Pirma"
    },

    'form_signature_note': {
        'en': "By signing, you confirm the information above is accurate.",
        'ar': "بتوقيعك، تؤكّد أن المعلومات أعلاه صحيحة.",
        'ur': "دستخط کر کے، آپ تصدیق کرتے ہیں کہ اوپر دی گئی معلومات درست ہیں۔",
        'tl': "Sa pamamagitan ng pagpirma, kinukumpirma mo na tama ang impormasyon sa itaas."
    },

    'form_clear': {
        'en': "Clear Signature",
        'ar': "مسح التوقيع",
        'ur': "دستخط صاف کریں",
        'tl': "Burahin ang Pirma"
    },

    'form_submit': {
        'en': "Submit Form",
        'ar': "إرسال النموذج",
        'ur': "فارم جمع کرائیں",
        'tl': "Isumite ang Form"
    },

    'form_submitted': {
        'en': "Form already submitted. Thank you!",
        'ar': "تم إرسال النموذج مسبقاً. شكراً لك!",
        'ur': "فارم پہلے ہی جمع ہو چکا ہے۔ شکریہ!",
        'tl': "Naisumite na ang form. Salamat!"
    },

    'form_invalid': {
        'en': "This link is invalid or has expired.",
        'ar': "هذا الرابط غير صالح أو منتهي الصلاحية.",
        'ur': "یہ لنک غیر درست ہے یا اس کی میعاد ختم ہو چکی ہے۔",
        'tl': "Hindi valid o nag-expire na ang link na ito."
    },

    'form_success': {
        'en': "Thank you! Your pre-visit form has been submitted successfully.",
        'ar': "شكراً لك! تم إرسال نموذج ما قبل الزيارة بنجاح.",
        'ur': "شکریہ! آپ کا پری وزٹ فارم کامیابی سے جمع ہو گیا ہے۔",
        'tl': "Salamat! Matagumpay na naisumite ang iyong pre-visit form."
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def t(key, lang='en', **kwargs):
    """Get translated message. Falls back to English if translation missing.
    Usage: t('greeting', 'ar')
           t('nice_to_meet', 'ar', name='Ahmed')
    """
    translations = TRANSLATIONS.get(key, {})
    text = translations.get(lang) or translations.get('en', f'[{key}]')
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def get_rtl_direction(lang):
    """Return 'rtl' for Arabic/Urdu, 'ltr' for others."""
    return 'rtl' if lang in ('ar', 'ur') else 'ltr'
