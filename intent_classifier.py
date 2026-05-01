"""
Smart intent classifier using TF-IDF-like scoring.
Supports 19 dental chatbot intents across English, Arabic, Urdu, and Tagalog.
Uses pattern scoring + structural signals to determine intent.
"""

import re
import math
from collections import Counter

# ── Intent definitions with weighted training examples ──
_INTENT_EXAMPLES = {
    "booking": {
        "weight": 1.2,
        "examples": [
            "I want to book an appointment",
            "I'd like to schedule a visit",
            "Can I make an appointment",
            "Book me a slot please",
            "I need to see a dentist",
            "Schedule an appointment for me",
            "I want to come in for a checkup",
            "Can I get an appointment tomorrow",
            "Book appointment",
            "I need a dental appointment",
            "Book me in",
            "Reserve a time slot",
            "Let's book",
            "I want to book",
            "Help me schedule",
            "Book now",
            "I want to schedule for tomorrow",
            "Set up an appointment please",
            "I want to book with Dr. Sarah on Monday",
            "Schedule me for teeth whitening",
            "Book me for a cleaning",
            "I need a consultation",
            "BOOK ME IN ASAP",
            "Book my son for braces consultation",
            "I need an emergency root canal today",
            "أريد حجز موعد",
            "أحتاج إلى موعد عند طبيب الأسنان",
            "مجھے اپوائنٹمنٹ چاہیے",
            "کیا میں کل آ سکتا ہوں",
            "Gusto ko mag-book ng appointment",
            "Kailangan ko ng dentista",
            # Spanish
            "Quiero reservar una cita",
            "Necesito una cita con el dentista",
            "Reservar una cita por favor",
            # French
            "Je voudrais prendre un rendez-vous",
            "J'ai besoin d'un rendez-vous dentaire",
            "Réserver un créneau s'il vous plaît",
            # Chinese
            "我想预约",
            "我需要看牙医",
            "帮我预约一下",
        ],
    },
    "availability": {
        "weight": 1.0,
        "examples": [
            "What slots are available today",
            "When can I come in",
            "What are your available times",
            "Are there any openings tomorrow",
            "What time is Dr. Smith free",
            "Show me available slots",
            "Is there anything on Monday",
            "Do you have morning slots",
            "What's available this week",
            "When is the doctor available",
            "What days is the doctor free",
            "Is the doctor available tomorrow",
            "Do you have evening appointments",
            "When can I get a root canal",
            "Any appointments on Friday",
            "ما هي المواعيد المتاحة اليوم",
            "متى يمكنني المجيء",
            "آج کون سا وقت دستیاب ہے",
            "ڈاکٹر کب فارغ ہیں",
            "Anong oras available ngayon",
            "May bukas na slot ba",
        ],
    },
    "doctor_info": {
        "weight": 1.0,
        "examples": [
            "Who are your doctors",
            "Tell me about your dentists",
            "Which doctor should I choose",
            "Compare your doctors",
            "Show me the doctors",
            "Who is the best dentist here",
            "What specialties do your doctors have",
            "Do you have a female dentist",
            "Is there an orthodontist",
            "Who does root canals",
            "Help me choose a doctor",
            "What doctors do you have",
            "List your doctors",
            "من هم أطباؤكم",
            "أريد مقارنة الأطباء",
            "اريد دكتور",
            "آپ کے ڈاکٹر کون ہیں",
            "Gusto ko malaman ang mga doktor",
        ],
    },
    "treatment_question": {
        "weight": 1.0,
        "examples": [
            "What is a root canal",
            "Does a root canal hurt",
            "How long does whitening last",
            "What is Invisalign",
            "How long do veneers last",
            "What causes tooth sensitivity",
            "How often should I get a cleaning",
            "Can you fix a chipped tooth",
            "What are braces",
            "How does teeth whitening work",
            "What are veneers",
            "How long do implants last",
            "Is teeth whitening safe",
            "What are crowns",
            "Do you sell toothpaste",
            "I'm pregnant is dental treatment safe",
            "I have diabetes can I get treatment",
            "I'm on blood thinners",
            "Can I eat before my appointment",
            "ما هو علاج قناة الجذر",
            "هل تقويم الأسنان مؤلم",
            "روٹ کینال کیا ہے",
            "Ano ang root canal",
        ],
    },
    "emergency": {
        "weight": 1.3,
        "examples": [
            "I have severe tooth pain",
            "My tooth broke",
            "I knocked out my tooth",
            "My jaw is very swollen",
            "I think I have an abscess",
            "Bleeding won't stop after extraction",
            "Can't sleep from tooth pain",
            "Tooth fell out",
            "Face is swollen from toothache",
            "Cracked tooth and in pain",
            "I was in a dental accident",
            "Severe sensitivity after procedure",
            "tooth brokn help",
            "I hav servere pain",
            "my tooth is killing me",
            "أسنانني تؤلمني بشدة",
            "كسرت سنة",
            "فكي منتفخ جداً",
            "Severe na sakit sa ngipin ko",
            "Nabali ang aking ngipin",
            "میرا دانت ٹوٹ گیا",
            # Spanish
            "Tengo un dolor de muelas muy fuerte",
            "Se me rompió un diente",
            "Es una emergencia dental",
            # French
            "J'ai une douleur dentaire très forte",
            "Ma dent s'est cassée",
            "C'est une urgence dentaire",
            # Chinese
            "我牙疼得厉害",
            "我的牙齿断了",
            "牙齿紧急情况",
        ],
    },
    "greeting": {
        "weight": 1.0,
        "examples": [
            "Hi", "Hello", "Hey", "Good morning", "Good afternoon",
            "Good evening", "Hi there", "Hey there", "Greetings",
            "What's up", "Hiya", "Good day", "Howdy",
            "hi can u help me pls",
            "hello there",
            "مرحبا", "السلام عليكم", "اهلا",
            "السلام علیکم", "ہیلو",
            "Kamusta", "Hello po",
            # Spanish
            "Hola", "Buenos días", "Buenas tardes",
            # French
            "Bonjour", "Salut", "Bonsoir",
            # Chinese
            "你好", "您好", "早上好",
        ],
    },
    "farewell": {
        "weight": 1.0,
        "examples": [
            "Bye", "Goodbye", "Thank you", "Thanks a lot",
            "That's all I needed", "Have a good day", "See you soon",
            "Thanks for your help", "Goodbye for now", "All done",
            "That's everything", "No more questions", "Take care",
            "See you later", "Bye bye", "Thanks bye",
            "شكراً", "مع السلامة", "الله حافظ",
            "شکریہ", "Salamat", "Paalam",
            # Spanish
            "Adiós", "Gracias", "Hasta luego",
            # French
            "Au revoir", "Merci", "Bonne journée",
            # Chinese
            "再见", "谢谢", "拜拜",
        ],
    },
    "cancellation": {
        "weight": 1.2,
        "examples": [
            "I need to cancel my appointment",
            "Cancel my booking for tomorrow",
            "I can't make it on Monday",
            "I want to reschedule my appointment",
            "Can I change my appointment time",
            "I need to postpone my visit",
            "Please cancel my appointment with Dr. Smith",
            "Move my appointment to next week",
            "Something came up need to cancel",
            "I'm running late can I reschedule",
            "Cancel all my upcoming appointments",
            "أريد إلغاء موعدي",
            "لا أستطيع الحضور غداً",
            "أريد تأجيل الموعد",
            "میں اپنی اپوائنٹمنٹ منسوخ کرنا چاہتا ہوں",
            "Kailangan ko i-cancel ang appointment",
            "Hindi ako makakadating bukas",
            # Spanish
            "Quiero cancelar mi cita",
            "Necesito reprogramar mi cita",
            # French
            "Je veux annuler mon rendez-vous",
            "Je dois reporter mon rendez-vous",
            # Chinese
            "我想取消预约",
            "我需要改期",
        ],
    },
    "pricing_insurance": {
        "weight": 1.0,
        "examples": [
            "How much does a cleaning cost",
            "What's the price for teeth whitening",
            "How much is a root canal",
            "What does an implant cost",
            "Price for braces",
            "How much is a filling",
            "What's the crown cost",
            "Do you accept insurance",
            "What insurance do you take",
            "Is Tawuniya accepted",
            "Do you take BUPA",
            "how mcuh cleaning",
            "What are your payment options",
            "كم تكلفة تنظيف الأسنان",
            "هل تقبلون التأمين الصحي",
            "كم سعر التقويم",
            "دانت کی صفائی کتنی مہنگی ہے",
            "Magkano ang cleaning",
            "Tumatanggap ba kayo ng insurance",
        ],
    },
    "clinic_info": {
        "weight": 1.0,
        "examples": [
            "What are your opening hours",
            "Are you open on Saturday",
            "What time do you close",
            "Are you open today",
            "Where are you located",
            "What's your address",
            "Do you have parking",
            "How do I get to your clinic",
            "What are your holiday hours",
            "Do you work on Sundays",
            "Are you open during Ramadan",
            "Are you a real clinic or online only",
            "ما هي ساعات العمل",
            "هل أنتم مفتوحون اليوم",
            "آپ کے اوقات کار کیا ہیں",
            "Anong oras kayo bukas",
            "Nasaan ang clinic",
        ],
    },
    "lead_capture": {
        "weight": 1.0,
        "examples": [
            "I'm just looking for now",
            "Not ready to book yet",
            "I want more information first",
            "Can someone call me back",
            "I'll think about it",
            "Send me more information",
            "I want a callback",
            "Just browsing",
            "Not sure yet need to think",
            "I need to discuss with my family first",
            "Call me back",
            "Here is my phone number",
            "Contact me later",
            "أريد التفكير أولاً",
            "أحتاج مزيداً من المعلومات",
            "ابھی بک نہیں کرنا",
            "Mag-iisip muna ako",
            "Hindi pa ako handa mag-book",
        ],
    },
    "waitlist": {
        "weight": 1.1,
        "examples": [
            "Add me to the waitlist",
            "I want to join the waitlist",
            "Is there a waitlist",
            "Put me on the waiting list",
            "Remove me from the waitlist",
            "How does the waitlist work",
            "What position am I in the waitlist",
            "How long will I wait",
            "Can I be on multiple waitlists",
            "أضفني إلى قائمة الانتظار",
            "كيف تعمل قائمة الانتظار",
            "مجھے ویٹ لسٹ میں ڈالیں",
            "Ilagay ako sa waitlist",
            "Paano gumagana ang waitlist",
        ],
    },
    "promotions": {
        "weight": 1.0,
        "examples": [
            "Do you have any discounts",
            "Is there a promo code",
            "I have a discount code",
            "Do you offer student discounts",
            "First time patient discount",
            "Apply discount code SAVE20",
            "Code not working",
            "Is the promo still valid",
            "Any Ramadan deals",
            "هل هناك خصومات متاحة",
            "هل كودي لا يزال صالحاً",
            "کیا کوئی ڈسکاؤنٹ ہے",
            "May promo ba kayo",
            "May discount para sa bagong pasyente",
        ],
    },
    "loyalty": {
        "weight": 1.0,
        "examples": [
            "How many loyalty points do I have",
            "How does the loyalty program work",
            "Can I use my points",
            "How do I earn more points",
            "What are my points worth",
            "Do my points expire",
            "I referred a friend",
            "I want to redeem my points",
            "كم نقطة أملك",
            "كيف يعمل برنامج الولاء",
            "میرے کتنے لوائلٹی پوائنٹس ہیں",
            "Ilang loyalty points mayroon ako",
        ],
    },
    "pre_visit_form": {
        "weight": 1.0,
        "examples": [
            "I received a form link",
            "How do I fill the pre-visit form",
            "I already submitted my form",
            "Do I need to fill a form",
            "Can I fill the form at the clinic",
            "What information does the form ask for",
            "Is the form secure",
            "The form link isn't working",
            "تلقيت رابط نموذج",
            "كيف أملأ النموذج",
            "میں نے فارم بھیج دیا ہے",
            "Nakatanggap ako ng form link",
        ],
    },
    "recall": {
        "weight": 1.0,
        "examples": [
            "When should I come back",
            "When is my next appointment due",
            "I got a recall message",
            "Stop sending me reminders",
            "It's been a while since my last visit",
            "I got a birthday message from you",
            "I received a follow-up for my implant",
            "تلقيت رسالة متابعة",
            "متى يجب أن أعود",
            "مجھے ریکال میسج ملا",
            "Nakatanggap ako ng recall message",
        ],
    },
    "symptom_question": {
        "weight": 1.0,
        "examples": [
            "My tooth hurts when I eat",
            "My gums are bleeding",
            "My jaw clicks when I open it",
            "I have a toothache",
            "I have bad breath",
            "My teeth are getting shorter",
            "I grind my teeth at night",
            "My child's tooth is loose",
            "There's a bump on my gum",
            "I have a white spot on my gum",
            "I have a dental phobia",
            "أسنانني حساسة للبرد",
            "لثتي تنزف عند التفريش",
            "میرے دانت کھانے میں درد کرتے ہیں",
            "میرے مسوڑوں سے خون آتا ہے",
            "Masakit ang aking ngipin kapag kumakain",
            "Dumudugo ang aking gilagid",
        ],
    },
    "human_handoff": {
        "weight": 1.1,
        "examples": [
            "I want to speak to a human",
            "Can I speak to a real person",
            "Get me a human agent",
            "I need to speak to the clinic",
            "This is urgent I need a person",
            "Your AI isn't helping me",
            "I don't understand your answers",
            "Connect me to staff",
            "Talk to a real person",
            "أريد التحدث مع شخص حقيقي",
            "تحدث مع الموظف",
            "میں انسان سے بات کرنا چاہتا ہوں",
            "Gusto ko makausap ang isang tao",
            # Spanish
            "Quiero hablar con una persona real",
            "Necesito hablar con alguien",
            "Conéctame con un agente",
            # French
            "Je veux parler à une vraie personne",
            "Connectez-moi à un agent",
            "J'ai besoin de parler à quelqu'un",
            # Chinese
            "我想和真人说话",
            "请转接人工客服",
            "我需要和人工交谈",
        ],
    },
    "complaint": {
        "weight": 1.0,
        "examples": [
            "I'm not happy with my last visit",
            "The doctor was rude",
            "I waited too long",
            "The treatment didn't work",
            "I want a refund",
            "Your chatbot is useless",
            "I'm going to leave a bad review",
            "Bad experience",
            "Not satisfied with the service",
            "غير راضٍ عن الخدمة",
            "الطبيب لم يكن محترماً",
            "میں آخری دورے سے خوش نہیں ہوں",
            "Hindi ako nasisiyahan sa serbisyo",
        ],
    },
    "appointment_reminder": {
        "weight": 1.1,
        "examples": [
            "Remind me about my appointment",
            "When is my next appointment",
            "Send me a reminder",
            "I want appointment reminders",
            "Can you confirm my appointment",
            "What time is my booking",
            "Did I get a confirmation",
            "I need a reminder for my visit",
            "Appointment confirmation please",
            "When do I need to come in",
            "Set up reminders for my appointment",
            "Do you send appointment reminders",
            "Can I get an SMS reminder",
            "Email me my appointment details",
            "ذكرني بموعدي",
            "متى موعدي القادم",
            "مجھے اپنی ملاقات کی یاد دہانی چاہیے",
            "Paalalahanan mo ako sa appointment ko",
        ],
    },
    "survey_feedback": {
        "weight": 1.0,
        "examples": [
            "I want to give feedback",
            "How do I rate my experience",
            "Leave a review",
            "I want to review my visit",
            "Rate my appointment",
            "Give feedback about the doctor",
            "I have feedback about my treatment",
            "Where can I leave a review",
            "I want to rate the clinic",
            "Patient satisfaction survey",
            "How was my experience form",
            "Can I share my opinion",
            "أريد أن أعطي تقييم",
            "كيف أقيم تجربتي",
            "میں اپنا تجربہ شیئر کرنا چاہتا ہوں",
            "Gusto kong mag-rate ng experience ko",
        ],
    },
    "treatment_package": {
        "weight": 1.0,
        "examples": [
            "Do you have any packages",
            "Treatment packages available",
            "Bundle deals for treatments",
            "Package offers",
            "What packages do you offer",
            "Is there a cleaning package",
            "Whitening package price",
            "Dental care package",
            "How much for the full package",
            "Any combo deals",
            "Treatment bundle discount",
            "I want to buy a package",
            "Family dental package",
            "هل لديكم باقات علاجية",
            "ما هي العروض المتوفرة",
            "پیکیج کی قیمت کیا ہے",
            "May package ba kayo",
        ],
    },
    "invoice_receipt": {
        "weight": 1.0,
        "examples": [
            "I need my invoice",
            "Send me the receipt",
            "Can I get a receipt",
            "Invoice for my appointment",
            "I need a tax invoice",
            "Print my receipt",
            "Email me the invoice",
            "Payment receipt please",
            "How much did I pay",
            "I need proof of payment",
            "VAT invoice",
            "ZATCA compliant invoice",
            "أريد الفاتورة",
            "أرسل لي الإيصال",
            "مجھے رسید چاہیے",
            "Kailangan ko ng resibo",
        ],
    },
    "noshow_reschedule": {
        "weight": 1.0,
        "examples": [
            "I missed my appointment",
            "I couldn't make it to my appointment",
            "Sorry I missed my booking",
            "I forgot my appointment",
            "Can I reschedule my missed appointment",
            "I was a no-show",
            "I need to reschedule",
            "Something came up and I missed it",
            "I want to rebook after missing",
            "Sorry I didn't show up",
            "Reschedule my cancelled appointment",
            "فاتني موعدي",
            "أريد إعادة الحجز",
            "میں اپنی ملاقات میں نہیں آ سکا",
            "Hindi ako nakapunta sa appointment",
        ],
    },
    "doctor_portal": {
        "weight": 0.9,
        "examples": [
            "Doctor portal",
            "Doctor dashboard",
            "My doctor schedule",
            "I am a doctor here",
            "Doctor login",
            "Access my doctor panel",
            "View my patient list",
            "Doctor self management",
            "My schedule as a doctor",
            "Doctor availability settings",
            "بوابة الطبيب",
            "لوحة تحكم الدكتور",
            "ڈاکٹر پورٹل",
        ],
    },
    "upsell_addon": {
        "weight": 0.9,
        "examples": [
            "What else do you recommend",
            "Any add-on treatments",
            "Should I get whitening too",
            "What goes well with cleaning",
            "Any other treatments you suggest",
            "Recommended additional services",
            "What should I add to my appointment",
            "Complementary treatments",
            "Upgrade my treatment",
            "ماذا تنصحون أيضاً",
            "کیا آپ کچھ اور تجویز کرتے ہیں",
            "Ano pa ang recommended",
        ],
    },
    "channel_inbox": {
        "weight": 0.8,
        "examples": [
            "I messaged you on WhatsApp",
            "Check your Instagram messages",
            "I sent a Facebook message",
            "Reply to my WhatsApp",
            "I contacted you on social media",
            "Check your inbox",
            "I left a message on Facebook",
            "Did you get my WhatsApp message",
            "راسلتكم على الواتساب",
            "چیک کریں واٹس ایپ",
            "Nag-message ako sa WhatsApp",
        ],
    },
    "performance_report": {
        "weight": 0.8,
        "examples": [
            "Monthly performance report",
            "Show me clinic statistics",
            "How did we do this month",
            "Booking analytics",
            "Revenue report",
            "No-show rate this month",
            "Doctor performance stats",
            "Generate monthly report",
            "Clinic performance",
            "تقرير الأداء الشهري",
            "ماہانہ رپورٹ",
            "Monthly report po",
        ],
    },
    "whitelabel_branding": {
        "weight": 0.7,
        "examples": [
            "White label options",
            "Custom branding",
            "Remove ChatGenius branding",
            "Use my own logo",
            "Custom domain setup",
            "Brand customization",
            "White label chatbot",
            "My own branding",
            "Customize the appearance",
            "تخصيص العلامة التجارية",
            "برانڈنگ تبدیل کریں",
        ],
    },
}

# Stop words to skip during matching
_STOP_WORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "the", "a", "an", "is", "are", "was", "were", "am", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "shall", "can", "may", "might", "must", "to", "of", "in", "for", "on", "with",
    "at", "by", "from", "as", "into", "about", "and", "but", "or", "not", "no",
    "so", "if", "then", "that", "this", "there", "here", "up", "down", "out",
    "off", "over", "under", "again", "very", "just", "also", "only",
    "really", "much", "going", "get", "got", "go", "please", "tell",
    "know", "need", "want", "like", "help", "actually", "wondering",
    "quick", "question", "hey", "hi", "hello", "confirm",
    "yeah", "yes", "okay", "ok", "sure", "right", "well", "thing",
    "some", "any", "all", "each", "every", "both", "few", "more",
    "other", "same", "such", "than", "too", "when", "where", "while",
    # Spanish stop words
    "yo", "tu", "el", "ella", "nosotros", "ellos", "un", "una", "es", "son",
    "los", "las", "del", "al", "por", "para", "con", "sin", "sobre",
    "como", "pero", "más", "muy", "también", "ya", "que", "este", "esta",
    # French stop words
    "je", "tu", "il", "elle", "nous", "vous", "ils", "elles", "le", "la",
    "les", "un", "une", "des", "du", "de", "en", "dans", "sur", "pour",
    "avec", "est", "sont", "ce", "cette", "ces", "qui", "que", "ne", "pas",
    "plus", "aussi", "très", "bien", "oui", "non",
    # Chinese stop words (common particles)
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "这", "中", "大", "来", "上", "个", "到", "说", "们", "为", "子", "你",
    "会", "着", "没有", "看", "好", "自己", "么",
}

# ── Build index at import time ──
_idf = {}
_intent_vectors = {}
_ready = False


def _tokenize(text):
    """Tokenize text into meaningful words, keeping Arabic/Urdu/Tagalog/Chinese/Spanish/French chars."""
    if not text or not text.strip():
        return []
    text = re.sub(r'[^\w\s\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\u4E00-\u9FFF\u00C0-\u024F]', ' ', text.lower())
    # For Chinese: use bigram/trigram approach for better word segmentation
    tokens = []
    for w in text.split():
        if any('\u4e00' <= c <= '\u9fff' for c in w):
            # Extract CJK characters
            cjk_chars = [c for c in w if '\u4e00' <= c <= '\u9fff']
            # Add individual characters (excluding stop words)
            for c in cjk_chars:
                if c not in _STOP_WORDS:
                    tokens.append(c)
            # Add bigrams for better semantic matching
            for i in range(len(cjk_chars) - 1):
                bigram = cjk_chars[i] + cjk_chars[i + 1]
                if bigram not in _STOP_WORDS:
                    tokens.append(bigram)
            # Add trigrams for common multi-char words
            for i in range(len(cjk_chars) - 2):
                trigram = cjk_chars[i] + cjk_chars[i + 1] + cjk_chars[i + 2]
                tokens.append(trigram)
        elif w not in _STOP_WORDS and len(w) > 1:
            tokens.append(w)
    return tokens


def _build_index():
    """Build TF-IDF vectors for all intent examples."""
    global _idf, _intent_vectors, _ready

    all_docs = []
    doc_to_intent = []
    for intent_name, intent_data in _INTENT_EXAMPLES.items():
        for example in intent_data["examples"]:
            tokens = _tokenize(example)
            all_docs.append(tokens)
            doc_to_intent.append(intent_name)

    n_docs = len(all_docs)
    df = Counter()
    for doc in all_docs:
        for word in set(doc):
            df[word] += 1

    _idf = {}
    for word, freq in df.items():
        _idf[word] = math.log((n_docs + 1) / (freq + 1)) + 1

    _intent_vectors = {}
    for i, doc in enumerate(all_docs):
        intent_name = doc_to_intent[i]
        if intent_name not in _intent_vectors:
            _intent_vectors[intent_name] = []

        tf = Counter(doc)
        max_tf = max(tf.values()) if tf else 1
        vector = {}
        for word, count in tf.items():
            vector[word] = (0.5 + 0.5 * count / max_tf) * _idf.get(word, 1)
        _intent_vectors[intent_name].append(vector)

    _ready = True


def _cosine_similarity(vec1, vec2):
    """Compute cosine similarity between two sparse vectors."""
    common = set(vec1.keys()) & set(vec2.keys())
    if not common:
        return 0.0
    dot = sum(vec1[w] * vec2[w] for w in common)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def _keyword_boost(text):
    """Fast keyword-based boost signals for common patterns."""
    lower = text.lower().strip()
    boosts = {}

    # Emergency keywords — high priority
    if re.search(r'\b(severe|pain|broke|broken|bleeding|swollen|abscess|knocked out|fell out|accident|emergency|urgent|killing me)\b', lower):
        boosts["emergency"] = 0.3
    if re.search(r'\b(بشدة|كسر|منتفخ|نزيف|طوارئ|severe|sakit|nabali)\b', lower):
        boosts["emergency"] = boosts.get("emergency", 0) + 0.2

    # Cancellation keywords
    if re.search(r'\b(cancel|reschedule|postpone|change.*appointment|can\'t make it|move.*appointment)\b', lower):
        boosts["cancellation"] = 0.35
    if re.search(r'\b(إلغاء|تأجيل|منسوخ|i-cancel)\b', lower):
        boosts["cancellation"] = boosts.get("cancellation", 0) + 0.2

    # Waitlist keywords
    if re.search(r'\b(waitlist|waiting list|wait list)\b', lower):
        boosts["waitlist"] = 0.4

    # Loyalty keywords
    if re.search(r'\b(loyalty|points|redeem|reward)\b', lower):
        boosts["loyalty"] = 0.3
    if re.search(r'\b(نقاط|ولاء|لوائلٹی|پوائنٹس)\b', lower):
        boosts["loyalty"] = boosts.get("loyalty", 0) + 0.2

    # Promo keywords
    if re.search(r'\b(discount|promo|coupon|code|offer|deal)\b', lower):
        boosts["promotions"] = 0.3
    if re.search(r'\b(خصوم|ڈسکاؤنٹ|promo)\b', lower):
        boosts["promotions"] = boosts.get("promotions", 0) + 0.2

    # Human handoff keywords
    if re.search(r'\b(human|real person|speak to|talk to|agent|staff|live chat)\b', lower):
        boosts["human_handoff"] = 0.35
    if re.search(r'\b(شخص حقيقي|موظف|انسان)\b', lower):
        boosts["human_handoff"] = boosts.get("human_handoff", 0) + 0.2

    # Complaint keywords
    if re.search(r'\b(not happy|unhappy|rude|bad|terrible|refund|complaint|bad review|not satisfied|useless)\b', lower):
        boosts["complaint"] = 0.3

    # Form keywords
    if re.search(r'\b(form|pre.?visit|fill out|submit)\b', lower):
        boosts["pre_visit_form"] = 0.3

    # Recall keywords
    if re.search(r'\b(recall|reminder|follow.?up|come back|birthday message)\b', lower):
        boosts["recall"] = 0.3

    # Clinic info keywords
    if re.search(r'\b(hours?|open|close|location|address|parking|direction|ramadan)\b', lower):
        boosts["clinic_info"] = 0.2

    # Pricing/insurance keywords
    if re.search(r'\b(cost|price|how much|fee|payment|insurance|sar|tawuniya|bupa|medgulf|axa)\b', lower):
        boosts["pricing_insurance"] = 0.25

    # Lead capture signals
    if re.search(r'\b(not ready|think about|browsing|call.*back|callback|later|not sure)\b', lower):
        boosts["lead_capture"] = 0.25

    # Symptom keywords
    if re.search(r'\b(hurts|ache|bleeding gums|sensitive|grinding|loose tooth|bump|phobia)\b', lower):
        boosts["symptom_question"] = 0.2

    return boosts


def _structural_signals(text):
    """Analyze sentence structure to detect question vs action."""
    lower = text.lower().strip()
    signals = {}

    is_question_form = bool(
        "?" in text or
        re.match(r'^(what|how|why|when|where|who|which|is|are|do|does|can|could|will|would|tell|explain|show)\b', lower)
    )

    is_action_request = bool(
        re.search(r'\b(i want|i\'d like|i need|let\'s|lets|help me|book me|schedule me|can i get|add me|put me)\b', lower)
    )

    is_what_is = bool(re.match(r'^(what|how|when|where|who|which)\s+(is|are|does|do|was|were|can|could|will|would)\b', lower))

    if is_question_form and not is_action_request:
        signals["booking"] = -0.05
        signals["availability"] = 0.1
        signals["treatment_question"] = 0.1

    if is_what_is:
        signals["booking"] = signals.get("booking", 0) - 0.05
        signals["treatment_question"] = signals.get("treatment_question", 0) + 0.1

    if is_action_request:
        signals["booking"] = signals.get("booking", 0) + 0.2

    word_count = len(lower.split())
    if word_count <= 2:
        signals["greeting"] = signals.get("greeting", 0) + 0.15
        signals["farewell"] = signals.get("farewell", 0) + 0.15

    return signals


def classify(text, min_confidence=0.15):
    """
    Classify user message into one of 19 dental chatbot intents.

    Returns:
        tuple: (intent_name, confidence_score)
    """
    if not _ready:
        _build_index()

    # Handle empty/whitespace-only input gracefully
    if not text or not text.strip():
        return "greeting", 0.0

    tokens = _tokenize(text)

    # Handle very short messages (1-2 chars) — likely greetings or noise
    stripped = text.strip()
    if not tokens and len(stripped) <= 2:
        return "greeting", 0.3

    if not tokens:
        return "greeting", 0.0

    # Build query vector
    tf = Counter(tokens)
    max_tf = max(tf.values()) if tf else 1
    query_vec = {}
    for word, count in tf.items():
        query_vec[word] = (0.5 + 0.5 * count / max_tf) * _idf.get(word, 1)

    # Normalize weights so they sum to len(intents) — keeps relative ratios
    # but ensures no single weight dominates unfairly
    all_weights = [_INTENT_EXAMPLES[name]["weight"] for name in _intent_vectors]
    avg_weight = sum(all_weights) / len(all_weights) if all_weights else 1.0

    # Score each intent: best matching example * normalized intent weight
    intent_scores = {}
    for intent_name, examples in _intent_vectors.items():
        weight = _INTENT_EXAMPLES[intent_name]["weight"] / avg_weight
        best_sim = 0
        for doc_vec in examples:
            sim = _cosine_similarity(query_vec, doc_vec)
            if sim > best_sim:
                best_sim = sim
        intent_scores[intent_name] = best_sim * weight

    # Apply keyword boosts
    keyword_boosts = _keyword_boost(text)
    for intent_name, boost in keyword_boosts.items():
        if intent_name in intent_scores:
            intent_scores[intent_name] += boost

    # Apply structural signals
    signals = _structural_signals(text)
    for intent_name, boost in signals.items():
        if intent_name in intent_scores:
            intent_scores[intent_name] += boost

    # Pick the winner
    best_intent = max(intent_scores, key=intent_scores.get)
    best_score = intent_scores[best_intent]

    # Check confidence gap — if top two are too close, lower confidence
    sorted_scores = sorted(intent_scores.values(), reverse=True)
    if len(sorted_scores) >= 2:
        gap = sorted_scores[0] - sorted_scores[1]
        if gap < 0.05 and best_score < 0.4:
            # Ambiguous classification — reduce confidence
            best_score *= 0.8

    if best_score < min_confidence:
        return "greeting", best_score

    return best_intent, best_score


# Build index on import
_build_index()
