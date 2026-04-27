"""
Feature 9 -- Emergency Fast-Track Flow
=======================================
Handles dental emergencies with:
  1. Emergency keyword detection (English + Arabic)
  2. Condition-specific first-aid instructions (EN / AR / UR / TL)
  3. Fast-track booking (earliest slot within 3 hours)
  4. Dashboard alerts for clinic staff

Usage from app.py / smart_router.py:
    from emergency_handler import is_emergency, handle_emergency
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("emergency")

# ======================================================================
#  1. Emergency Keyword Detection
# ======================================================================

EMERGENCY_KEYWORDS = [
    # English
    'severe pain', "can't sleep from pain", 'cant sleep from pain',
    'broken tooth', 'knocked out tooth', 'tooth knocked out',
    'swollen jaw', 'swollen face', 'swelling',
    "bleeding won't stop", 'bleeding wont stop', 'non-stop bleeding', 'continuous bleeding',
    'tooth fell out', 'tooth came out', 'lost a tooth',
    'abscess', 'infection', 'pus',
    'accident', 'trauma', 'hit my tooth', 'cracked tooth',
    'emergency', 'urgent', 'unbearable pain',
    # Arabic
    '\u0623\u0644\u0645 \u0634\u062f\u064a\u062f',      # severe pain
    '\u062a\u0648\u0631\u0645',              # swelling
    '\u0646\u0632\u064a\u0641',              # bleeding
    '\u0643\u0633\u0631',               # fracture / broken
    '\u0637\u0648\u0627\u0631\u0626',            # emergency
    '\u0639\u0627\u062c\u0644',              # urgent
    '\u062e\u0644\u0639',               # extraction / knocked out
    '\u062e\u0631\u0627\u062c',              # abscess
    '\u0627\u0644\u062a\u0647\u0627\u0628',            # infection / inflammation
    '\u062d\u0627\u062f\u062b',              # accident
]


def is_emergency(message):
    """Check if a message contains emergency indicators.

    Returns:
        tuple: (bool, list[str]) -- whether message is an emergency and
               which keywords matched.
    """
    lower = message.lower()
    matched = [kw for kw in EMERGENCY_KEYWORDS if kw in lower]
    return len(matched) > 0, matched


# ======================================================================
#  2. First-Aid Instructions  (EN / AR / UR / TL)
# ======================================================================

FIRST_AID = {
    'knocked_out_tooth': {
        'keywords': ['knocked out', 'tooth fell out', 'tooth came out',
                     'lost a tooth', '\u062e\u0644\u0639'],
        'en': (
            "**Knocked Out Tooth \u2014 Do This Now:**\n"
            "\u2022 Pick up the tooth by the crown (white part), NOT the root\n"
            "\u2022 If dirty, rinse gently with milk \u2014 do NOT scrub\n"
            "\u2022 Try to place it back in the socket and bite down gently\n"
            "\u2022 If you can\u2019t reinsert it, keep it in milk or between your cheek and gum\n"
            "\u2022 **Time is critical \u2014 come in within 30 minutes for the best chance of saving it**"
        ),
        'ar': (
            "**\u0633\u0646 \u0645\u062e\u0644\u0648\u0639 \u2014 \u0627\u0641\u0639\u0644 \u0647\u0630\u0627 \u0627\u0644\u0622\u0646:**\n"
            "\u2022 \u0627\u0645\u0633\u0643 \u0627\u0644\u0633\u0646 \u0645\u0646 \u0627\u0644\u062a\u0627\u062c (\u0627\u0644\u062c\u0632\u0621 \u0627\u0644\u0623\u0628\u064a\u0636)\u060c \u0648\u0644\u064a\u0633 \u0627\u0644\u062c\u0630\u0631\n"
            "\u2022 \u0625\u0630\u0627 \u0643\u0627\u0646 \u0645\u062a\u0633\u062e\u0627\u064b\u060c \u0627\u0634\u0637\u0641\u0647 \u0628\u0627\u0644\u062d\u0644\u064a\u0628 \u0628\u0631\u0641\u0642 \u2014 \u0644\u0627 \u062a\u0641\u0631\u0643\u0647\n"
            "\u2022 \u062d\u0627\u0648\u0644 \u0625\u0639\u0627\u062f\u062a\u0647 \u0641\u064a \u0645\u0643\u0627\u0646\u0647 \u0648\u0627\u0639\u0636\u0651 \u0639\u0644\u064a\u0647 \u0628\u0631\u0641\u0642\n"
            "\u2022 \u0625\u0630\u0627 \u0644\u0645 \u062a\u0633\u062a\u0637\u0639 \u0625\u0639\u0627\u062f\u062a\u0647\u060c \u0636\u0639\u0647 \u0641\u064a \u062d\u0644\u064a\u0628 \u0623\u0648 \u0628\u064a\u0646 \u062e\u062f\u0643 \u0648\u0644\u062b\u062a\u0643\n"
            "\u2022 **\u0627\u0644\u0648\u0642\u062a \u062d\u0631\u062c \u2014 \u062a\u0639\u0627\u0644 \u062e\u0644\u0627\u0644 \u0663\u0660 \u062f\u0642\u064a\u0642\u0629 \u0644\u0623\u0641\u0636\u0644 \u0641\u0631\u0635\u0629 \u0644\u0625\u0646\u0642\u0627\u0630 \u0627\u0644\u0633\u0646**"
        ),
        'ur': (
            "**\u062f\u0627\u0646\u062a \u0679\u0648\u0679 \u06af\u06cc\u0627 \u2014 \u0627\u0628\u06be\u06cc \u06cc\u06c1 \u06a9\u0631\u06cc\u06ba:**\n"
            "\u2022 \u062f\u0627\u0646\u062a \u06a9\u0648 \u062a\u0627\u062c (\u0633\u0641\u06cc\u062f \u062d\u0635\u06c1) \u0633\u06d2 \u067e\u06a9\u0691\u06cc\u06ba\u060c \u062c\u0691 \u0633\u06d2 \u0646\u06c1\u06cc\u06ba\n"
            "\u2022 \u0627\u06af\u0631 \u06af\u0646\u062f\u0627 \u06c1\u0648 \u062a\u0648 \u062f\u0648\u062f\u06be \u0633\u06d2 \u0622\u06c1\u0633\u062a\u06c1 \u062f\u06be\u0648\u0626\u06cc\u06ba \u2014 \u0631\u06af\u0691\u06cc\u06ba \u0645\u062a\n"
            "\u2022 \u0627\u0633\u06d2 \u0648\u0627\u067e\u0633 \u062c\u06af\u06c1 \u067e\u0631 \u0644\u06af\u0627\u0646\u06d2 \u06a9\u06cc \u06a9\u0648\u0634\u0634 \u06a9\u0631\u06cc\u06ba \u0627\u0648\u0631 \u0622\u06c1\u0633\u062a\u06c1 \u0633\u06d2 \u062f\u0628\u0627\u0626\u06cc\u06ba\n"
            "\u2022 \u0627\u06af\u0631 \u0648\u0627\u067e\u0633 \u0646\u06c1 \u0644\u06af\u0627 \u0633\u06a9\u06cc\u06ba \u062a\u0648 \u062f\u0648\u062f\u06be \u0645\u06cc\u06ba \u06cc\u0627 \u06af\u0627\u0644 \u0627\u0648\u0631 \u0645\u0633\u0648\u0691\u06d2 \u06a9\u06d2 \u062f\u0631\u0645\u06cc\u0627\u0646 \u0631\u06a9\u06be\u06cc\u06ba\n"
            "\u2022 **\u0648\u0642\u062a \u0628\u06c1\u062a \u0627\u06c1\u0645 \u06c1\u06d2 \u2014 \u06f3\u06f0 \u0645\u0646\u0679 \u0645\u06cc\u06ba \u0622\u0626\u06cc\u06ba**"
        ),
    },
    'severe_pain': {
        'keywords': ['severe pain', "can't sleep", 'cant sleep',
                     'unbearable', '\u0623\u0644\u0645 \u0634\u062f\u064a\u062f'],
        'en': (
            "**Severe Tooth Pain \u2014 Do This Now:**\n"
            "\u2022 Rinse your mouth with warm salt water (1 tsp salt in 8oz water)\n"
            "\u2022 Take over-the-counter pain relief (ibuprofen is best for dental pain)\n"
            "\u2022 Apply a cold pack to the outside of your cheek \u2014 10 min on, 10 min off\n"
            "\u2022 Avoid very hot or very cold food and drinks\n"
            "\u2022 Do NOT put aspirin directly on your gum \u2014 it can burn the tissue"
        ),
        'ar': (
            "**\u0623\u0644\u0645 \u0623\u0633\u0646\u0627\u0646 \u0634\u062f\u064a\u062f \u2014 \u0627\u0641\u0639\u0644 \u0647\u0630\u0627 \u0627\u0644\u0622\u0646:**\n"
            "\u2022 \u0627\u0634\u0637\u0641 \u0641\u0645\u0643 \u0628\u0645\u0627\u0621 \u062f\u0627\u0641\u0626 \u0645\u0639 \u0645\u0644\u062d (\u0645\u0644\u0639\u0642\u0629 \u0635\u063a\u064a\u0631\u0629 \u0645\u0644\u062d \u0641\u064a \u0643\u0648\u0628 \u0645\u0627\u0621)\n"
            "\u2022 \u062a\u0646\u0627\u0648\u0644 \u0645\u0633\u0643\u0646 \u0623\u0644\u0645 (\u0627\u0644\u0625\u064a\u0628\u0648\u0628\u0631\u0648\u0641\u064a\u0646 \u0647\u0648 \u0627\u0644\u0623\u0641\u0636\u0644 \u0644\u0623\u0644\u0645 \u0627\u0644\u0623\u0633\u0646\u0627\u0646)\n"
            "\u2022 \u0636\u0639 \u0643\u0645\u0627\u062f\u0629 \u0628\u0627\u0631\u062f\u0629 \u0639\u0644\u0649 \u062e\u062f\u0643 \u2014 \u0661\u0660 \u062f\u0642\u0627\u0626\u0642 \u062b\u0645 \u0623\u0632\u0644\u0647\u0627 \u0661\u0660 \u062f\u0642\u0627\u0626\u0642\n"
            "\u2022 \u062a\u062c\u0646\u0628 \u0627\u0644\u0623\u0637\u0639\u0645\u0629 \u0648\u0627\u0644\u0645\u0634\u0631\u0648\u0628\u0627\u062a \u0634\u062f\u064a\u062f\u0629 \u0627\u0644\u062d\u0631\u0627\u0631\u0629 \u0623\u0648 \u0627\u0644\u0628\u0631\u0648\u062f\u0629\n"
            "\u2022 \u0644\u0627 \u062a\u0636\u0639 \u0627\u0644\u0623\u0633\u0628\u0631\u064a\u0646 \u0645\u0628\u0627\u0634\u0631\u0629 \u0639\u0644\u0649 \u0627\u0644\u0644\u062b\u0629 \u2014 \u0642\u062f \u064a\u062d\u0631\u0642 \u0627\u0644\u0623\u0646\u0633\u062c\u0629"
        ),
        'ur': (
            "**\u0634\u062f\u06cc\u062f \u062f\u0627\u0646\u062a \u062f\u0631\u062f \u2014 \u0627\u0628\u06be\u06cc \u06cc\u06c1 \u06a9\u0631\u06cc\u06ba:**\n"
            "\u2022 \u06af\u0631\u0645 \u0646\u0645\u06a9\u06cc\u0646 \u067e\u0627\u0646\u06cc \u0633\u06d2 \u06a9\u0644\u06cc \u06a9\u0631\u06cc\u06ba (1 \u0686\u0645\u0686 \u0646\u0645\u06a9 \u0627\u06cc\u06a9 \u06af\u0644\u0627\u0633 \u067e\u0627\u0646\u06cc \u0645\u06cc\u06ba)\n"
            "\u2022 \u062f\u0631\u062f \u06a9\u06cc \u062f\u0648\u0627\u0626\u06cc \u0644\u06cc\u06ba (\u0622\u0626\u0628\u0648\u067e\u0631\u0648\u0641\u06cc\u0646 \u062f\u0627\u0646\u062a\u0648\u06ba \u06a9\u06d2 \u062f\u0631\u062f \u06a9\u06d2 \u0644\u06cc\u06d2 \u0628\u06c1\u062a\u0631\u06cc\u0646 \u06c1\u06d2)\n"
            "\u2022 \u06af\u0627\u0644 \u06a9\u06d2 \u0628\u0627\u06c1\u0631 \u0679\u06be\u0646\u0688\u06cc \u067e\u0679\u06cc \u0644\u06af\u0627\u0626\u06cc\u06ba \u2014 10 \u0645\u0646\u0679 \u0644\u06af\u0627\u0626\u06cc\u06ba\u060c 10 \u0645\u0646\u0679 \u06c1\u0679\u0627\u0626\u06cc\u06ba\n"
            "\u2022 \u0628\u06c1\u062a \u06af\u0631\u0645 \u06cc\u0627 \u0628\u06c1\u062a \u0679\u06be\u0646\u0688\u06d2 \u06a9\u06be\u0627\u0646\u06d2 \u067e\u06cc\u0646\u06d2 \u0633\u06d2 \u067e\u0631\u06c1\u06cc\u0632 \u06a9\u0631\u06cc\u06ba\n"
            "\u2022 \u0627\u06cc\u0633\u067e\u0631\u0646 \u0633\u06cc\u062f\u06be\u06d2 \u0645\u0633\u0648\u0691\u06d2 \u067e\u0631 \u0645\u062a \u0644\u06af\u0627\u0626\u06cc\u06ba \u2014 \u06cc\u06c1 \u0679\u0634\u0648 \u062c\u0644\u0627 \u0633\u06a9\u062a\u06cc \u06c1\u06d2"
        ),
    },
    'swelling': {
        'keywords': ['swollen', 'swelling', '\u062a\u0648\u0631\u0645'],
        'en': (
            "**Facial Swelling \u2014 Do This Now:**\n"
            "\u2022 Apply a cold pack to the outside of your cheek \u2014 10 minutes on, 10 minutes off\n"
            "\u2022 Do NOT apply heat \u2014 it can make swelling worse\n"
            "\u2022 Take ibuprofen for pain and inflammation\n"
            "\u2022 If swelling is spreading to your eye or neck, or you have difficulty "
            "breathing or swallowing \u2192 **go to the emergency room immediately**"
        ),
        'ar': (
            "**\u062a\u0648\u0631\u0645 \u0627\u0644\u0648\u062c\u0647 \u2014 \u0627\u0641\u0639\u0644 \u0647\u0630\u0627 \u0627\u0644\u0622\u0646:**\n"
            "\u2022 \u0636\u0639 \u0643\u0645\u0627\u062f\u0629 \u0628\u0627\u0631\u062f\u0629 \u0639\u0644\u0649 \u062e\u062f\u0643 \u2014 \u0661\u0660 \u062f\u0642\u0627\u0626\u0642 \u062b\u0645 \u0623\u0632\u0644\u0647\u0627 \u0661\u0660 \u062f\u0642\u0627\u0626\u0642\n"
            "\u2022 \u0644\u0627 \u062a\u0636\u0639 \u062d\u0631\u0627\u0631\u0629 \u2014 \u0642\u062f \u062a\u0632\u064a\u062f \u0627\u0644\u062a\u0648\u0631\u0645\n"
            "\u2022 \u062a\u0646\u0627\u0648\u0644 \u0625\u064a\u0628\u0648\u0628\u0631\u0648\u0641\u064a\u0646 \u0644\u0644\u0623\u0644\u0645 \u0648\u0627\u0644\u0627\u0644\u062a\u0647\u0627\u0628\n"
            "\u2022 \u0625\u0630\u0627 \u0627\u0645\u062a\u062f \u0627\u0644\u062a\u0648\u0631\u0645 \u0644\u0644\u0639\u064a\u0646 \u0623\u0648 \u0627\u0644\u0631\u0642\u0628\u0629\u060c \u0623\u0648 \u0648\u0627\u062c\u0647\u062a \u0635\u0639\u0648\u0628\u0629 \u0641\u064a \u0627\u0644\u062a\u0646\u0641\u0633 \u0623\u0648 \u0627\u0644\u0628\u0644\u0639 "
            "\u2192 **\u0627\u0630\u0647\u0628 \u0644\u063a\u0631\u0641\u0629 \u0627\u0644\u0637\u0648\u0627\u0631\u0626 \u0641\u0648\u0631\u0627\u064b**"
        ),
    },
    'bleeding': {
        'keywords': ['bleeding', '\u0646\u0632\u064a\u0641'],
        'en': (
            "**Bleeding Won\u2019t Stop \u2014 Do This Now:**\n"
            "\u2022 Bite down firmly on a piece of clean gauze or a wet tea bag for 20 minutes\n"
            "\u2022 Do NOT spit, rinse, or use a straw \u2014 this dislodges the clot\n"
            "\u2022 Keep your head elevated\n"
            "\u2022 If bleeding continues after 30 minutes of firm pressure \u2192 "
            "come in immediately or visit an ER"
        ),
        'ar': (
            "**\u0627\u0644\u0646\u0632\u064a\u0641 \u0644\u0627 \u064a\u062a\u0648\u0642\u0641 \u2014 \u0627\u0641\u0639\u0644 \u0647\u0630\u0627 \u0627\u0644\u0622\u0646:**\n"
            "\u2022 \u0627\u0639\u0636\u0651 \u0628\u0642\u0648\u0629 \u0639\u0644\u0649 \u0642\u0637\u0639\u0629 \u0634\u0627\u0634 \u0646\u0638\u064a\u0641\u0629 \u0623\u0648 \u0643\u064a\u0633 \u0634\u0627\u064a \u0645\u0628\u0644\u0644 \u0644\u0645\u062f\u0629 \u0662\u0660 \u062f\u0642\u064a\u0642\u0629\n"
            "\u2022 \u0644\u0627 \u062a\u0628\u0635\u0642 \u0623\u0648 \u062a\u0634\u0637\u0641 \u0623\u0648 \u062a\u0633\u062a\u062e\u062f\u0645 \u0645\u0635\u0627\u0635\u0629 \u2014 \u0647\u0630\u0627 \u064a\u0632\u064a\u0644 \u0627\u0644\u062c\u0644\u0637\u0629\n"
            "\u2022 \u0623\u0628\u0642\u0650 \u0631\u0623\u0633\u0643 \u0645\u0631\u0641\u0648\u0639\u0627\u064b\n"
            "\u2022 \u0625\u0630\u0627 \u0627\u0633\u062a\u0645\u0631 \u0627\u0644\u0646\u0632\u064a\u0641 \u0628\u0639\u062f \u0663\u0660 \u062f\u0642\u064a\u0642\u0629 \u0645\u0646 \u0627\u0644\u0636\u063a\u0637 \u2192 \u062a\u0639\u0627\u0644 \u0641\u0648\u0631\u0627\u064b \u0623\u0648 \u0627\u0630\u0647\u0628 \u0644\u0644\u0637\u0648\u0627\u0631\u0626"
        ),
    },
    'abscess_infection': {
        'keywords': ['abscess', 'infection', 'pus', '\u062e\u0631\u0627\u062c', '\u0627\u0644\u062a\u0647\u0627\u0628'],
        'en': (
            "**Possible Abscess/Infection \u2014 Do This Now:**\n"
            "\u2022 Rinse with warm salt water several times a day\n"
            "\u2022 Do NOT try to pop or drain the abscess yourself\n"
            "\u2022 Take over-the-counter pain relief\n"
            "\u2022 **An untreated abscess can spread and become life-threatening "
            "\u2014 this requires urgent dental care**"
        ),
        'ar': (
            "**\u062e\u0631\u0627\u062c/\u0627\u0644\u062a\u0647\u0627\u0628 \u0645\u062d\u062a\u0645\u0644 \u2014 \u0627\u0641\u0639\u0644 \u0647\u0630\u0627 \u0627\u0644\u0622\u0646:**\n"
            "\u2022 \u0627\u0634\u0637\u0641 \u0628\u0645\u0627\u0621 \u062f\u0627\u0641\u0626 \u0645\u0639 \u0645\u0644\u062d \u0639\u062f\u0629 \u0645\u0631\u0627\u062a \u0641\u064a \u0627\u0644\u064a\u0648\u0645\n"
            "\u2022 \u0644\u0627 \u062a\u062d\u0627\u0648\u0644 \u0641\u0642\u0621 \u0623\u0648 \u062a\u0635\u0631\u064a\u0641 \u0627\u0644\u062e\u0631\u0627\u062c \u0628\u0646\u0641\u0633\u0643\n"
            "\u2022 \u062a\u0646\u0627\u0648\u0644 \u0645\u0633\u06a9\u0646 \u0623\u0644\u0645\n"
            "\u2022 **\u0627\u0644\u062e\u0631\u0627\u062c \u063a\u064a\u0631 \u0627\u0644\u0645\u0639\u0627\u0644\u062c \u0642\u062f \u064a\u0646\u062a\u0634\u0631 \u0648\u064a\u0635\u0628\u062d \u062e\u0637\u0631\u0627\u064b \u0639\u0644\u0649 \u0627\u0644\u062d\u064a\u0627\u0629 "
            "\u2014 \u0647\u0630\u0627 \u064a\u062a\u0637\u0644\u0628 \u0631\u0639\u0627\u064a\u0629 \u0623\u0633\u0646\u0627\u0646 \u0639\u0627\u062c\u0644\u0629**"
        ),
    },
    'broken_cracked': {
        'keywords': ['broken tooth', 'cracked', 'chipped', '\u0643\u0633\u0631'],
        'en': (
            "**Broken/Cracked Tooth \u2014 Do This Now:**\n"
            "\u2022 Rinse your mouth gently with warm water\n"
            "\u2022 If there\u2019s bleeding, apply gauze for 10 minutes\n"
            "\u2022 Apply a cold pack to reduce swelling\n"
            "\u2022 Save any broken pieces \u2014 bring them with you\n"
            "\u2022 Cover any sharp edges with dental wax or sugar-free gum to protect your tongue"
        ),
        'ar': (
            "**\u0633\u0646 \u0645\u0643\u0633\u0648\u0631/\u0645\u062a\u0634\u0642\u0642 \u2014 \u0627\u0641\u0639\u0644 \u0647\u0630\u0627 \u0627\u0644\u0622\u0646:**\n"
            "\u2022 \u0627\u0634\u0637\u0641 \u0641\u0645\u0643 \u0628\u0631\u0641\u0642 \u0628\u0645\u0627\u0621 \u062f\u0627\u0641\u0626\n"
            "\u2022 \u0625\u0630\u0627 \u0643\u0627\u0646 \u0647\u0646\u0627\u0643 \u0646\u0632\u064a\u0641\u060c \u0636\u0639 \u0634\u0627\u0634\u0627\u064b \u0644\u0645\u062f\u0629 \u0661\u0660 \u062f\u0642\u0627\u0626\u0642\n"
            "\u2022 \u0636\u0639 \u0643\u0645\u0627\u062f\u0629 \u0628\u0627\u0631\u062f\u0629 \u0644\u062a\u0642\u0644\u064a\u0644 \u0627\u0644\u062a\u0648\u0631\u0645\n"
            "\u2022 \u0627\u062d\u062a\u0641\u0638 \u0628\u0623\u064a \u0642\u0637\u0639 \u0645\u0643\u0633\u0648\u0631\u0629 \u2014 \u0623\u062d\u0636\u0631\u0647\u0627 \u0645\u0639\u0643\n"
            "\u2022 \u063a\u0637\u0651\u0650 \u0623\u064a \u062d\u0648\u0627\u0641 \u062d\u0627\u062f\u0629 \u0628\u0634\u0645\u0639 \u0627\u0644\u0623\u0633\u0646\u0627\u0646 \u0623\u0648 \u0639\u0644\u0643\u0629 \u0628\u062f\u0648\u0646 \u0633\u0643\u0631 \u0644\u062d\u0645\u0627\u064a\u0629 \u0644\u0633\u0627\u0646\u0643"
        ),
    },
    'accident': {
        'keywords': ['accident', 'trauma', 'hit', '\u062d\u0627\u062f\u062b'],
        'en': (
            "**Dental Trauma/Accident \u2014 Do This Now:**\n"
            "\u2022 Check for loose or displaced teeth \u2014 do NOT try to force them back\n"
            "\u2022 Control bleeding with gentle pressure using clean gauze\n"
            "\u2022 Apply cold pack to reduce swelling\n"
            "\u2022 If you hit your head or lost consciousness \u2192 **go to the ER first**\n"
            "\u2022 Save any tooth fragments"
        ),
        'ar': (
            "**\u062d\u0627\u062f\u062b/\u0625\u0635\u0627\u0628\u0629 \u0623\u0633\u0646\u0627\u0646 \u2014 \u0627\u0641\u0639\u0644 \u0647\u0630\u0627 \u0627\u0644\u0622\u0646:**\n"
            "\u2022 \u062a\u062d\u0642\u0642 \u0645\u0646 \u0627\u0644\u0623\u0633\u0646\u0627\u0646 \u0627\u0644\u0645\u062a\u062e\u0644\u062e\u0644\u0629 \u0623\u0648 \u0627\u0644\u0645\u0632\u0627\u062d\u0629 \u2014 \u0644\u0627 \u062a\u062d\u0627\u0648\u0644 \u0625\u0639\u0627\u062f\u062a\u0647\u0627 \u0628\u0627\u0644\u0642\u0648\u0629\n"
            "\u2022 \u0633\u064a\u0637\u0631 \u0639\u0644\u0649 \u0627\u0644\u0646\u0632\u064a\u0641 \u0628\u0636\u063a\u0637 \u0644\u0637\u064a\u0641 \u0628\u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u0634\u0627\u0634 \u0646\u0638\u064a\u0641\n"
            "\u2022 \u0636\u0639 \u0643\u0645\u0627\u062f\u0629 \u0628\u0627\u0631\u062f\u0629 \u0644\u062a\u0642\u0644\u064a\u0644 \u0627\u0644\u062a\u0648\u0631\u0645\n"
            "\u2022 \u0625\u0630\u0627 \u0636\u0631\u0628\u062a \u0631\u0623\u0633\u0643 \u0623\u0648 \u0641\u0642\u062f\u062a \u0627\u0644\u0648\u0639\u064a \u2192 **\u0627\u0630\u0647\u0628 \u0644\u0644\u0637\u0648\u0627\u0631\u0626 \u0623\u0648\u0644\u0627\u064b**\n"
            "\u2022 \u0627\u062d\u062a\u0641\u0638 \u0628\u0623\u064a \u0634\u0638\u0627\u064a\u0627 \u0623\u0633\u0646\u0627\u0646"
        ),
    },
}

# Generic / fallback first-aid advice per language
_GENERIC_FIRST_AID = {
    'en': (
        "**While you wait:**\n"
        "\u2022 Rinse with warm salt water\n"
        "\u2022 Take over-the-counter pain relief if needed\n"
        "\u2022 Apply a cold pack to the outside of your cheek\n"
        "\u2022 Avoid hot, cold, or hard foods"
    ),
    'ar': (
        "**\u0623\u062b\u0646\u0627\u0621 \u0627\u0644\u0627\u0646\u062a\u0638\u0627\u0631:**\n"
        "\u2022 \u0627\u0634\u0637\u0641 \u0628\u0645\u0627\u0621 \u062f\u0627\u0641\u0626 \u0645\u0639 \u0645\u0644\u062d\n"
        "\u2022 \u062a\u0646\u0627\u0648\u0644 \u0645\u0633\u0643\u0646 \u0623\u0644\u0645 \u0625\u0630\u0627 \u0644\u0632\u0645 \u0627\u0644\u0623\u0645\u0631\n"
        "\u2022 \u0636\u0639 \u0643\u0645\u0627\u062f\u0629 \u0628\u0627\u0631\u062f\u0629 \u0639\u0644\u0649 \u062e\u062f\u0643\n"
        "\u2022 \u062a\u062c\u0646\u0628 \u0627\u0644\u0623\u0637\u0639\u0645\u0629 \u0627\u0644\u062d\u0627\u0631\u0629 \u0648\u0627\u0644\u0628\u0627\u0631\u062f\u0629 \u0648\u0627\u0644\u0635\u0644\u0628\u0629"
    ),
    'ur': (
        "**\u0627\u0646\u062a\u0638\u0627\u0631 \u06a9\u06d2 \u062f\u0648\u0631\u0627\u0646:**\n"
        "\u2022 \u06af\u0631\u0645 \u0646\u0645\u06a9\u06cc\u0646 \u067e\u0627\u0646\u06cc \u0633\u06d2 \u06a9\u0644\u06cc \u06a9\u0631\u06cc\u06ba\n"
        "\u2022 \u0636\u0631\u0648\u0631\u062a \u06c1\u0648 \u062a\u0648 \u062f\u0631\u062f \u06a9\u06cc \u062f\u0648\u0627\u0626\u06cc \u0644\u06cc\u06ba\n"
        "\u2022 \u06af\u0627\u0644 \u06a9\u06d2 \u0628\u0627\u06c1\u0631 \u0679\u06be\u0646\u0688\u06cc \u067e\u0679\u06cc \u0644\u06af\u0627\u0626\u06cc\u06ba\n"
        "\u2022 \u06af\u0631\u0645\u060c \u0679\u06be\u0646\u0688\u06d2 \u06cc\u0627 \u0633\u062e\u062a \u06a9\u06be\u0627\u0646\u06d2 \u0633\u06d2 \u067e\u0631\u06c1\u06cc\u0632 \u06a9\u0631\u06cc\u06ba"
    ),
    'tl': (
        "**Habang naghihintay:**\n"
        "\u2022 Mag-mumog ng mainit na tubig na may asin\n"
        "\u2022 Uminom ng gamot pampawala ng sakit kung kailangan\n"
        "\u2022 Maglagay ng malamig na compress sa labas ng pisngi\n"
        "\u2022 Iwasan ang mainit, malamig, o matitigas na pagkain"
    ),
}


def get_first_aid(message, lang='en'):
    """Match the emergency message to the best first-aid instructions.

    Scores each condition by how many of its keywords appear in the
    message and returns the highest-scoring match.  Falls back to
    generic advice when no specific condition matches.

    Args:
        message: The user's message text.
        lang: Language code ('en', 'ar', 'ur', 'tl').

    Returns:
        str: Formatted first-aid instructions.
    """
    lower = message.lower()
    best_match = None
    best_score = 0

    for condition, data in FIRST_AID.items():
        score = sum(1 for kw in data['keywords'] if kw in lower)
        if score > best_score:
            best_score = score
            best_match = condition

    if best_match:
        aid = FIRST_AID[best_match]
        return aid.get(lang, aid.get('en', ''))

    return _GENERIC_FIRST_AID.get(lang, _GENERIC_FIRST_AID['en'])


# ======================================================================
#  3. Emergency Flow Handler
# ======================================================================

def handle_emergency(message, admin_id, session_data, lang='en'):
    """Process an emergency message end-to-end.

    Performs keyword detection, selects first-aid advice, searches for
    the earliest available slot within 3 hours, and creates a dashboard
    alert for clinic staff.

    Args:
        message:      The raw user message.
        admin_id:     Clinic admin ID (for doctor/slot lookups).
        session_data: Current chat session dict (must have at least 'name').
        lang:         Language code ('en', 'ar', 'ur', 'tl').

    Returns:
        dict with keys:
            response     -- chatbot reply text
            is_emergency -- True
            first_aid    -- first-aid instructions text
            alert        -- dict for dashboard notification
            ui_options   -- dict for frontend (slot selection / call button)
        Returns None if the message is not an emergency.
    """
    import database as db

    is_emerg, matched = is_emergency(message)
    if not is_emerg:
        return None

    first_aid = get_first_aid(message, lang)

    # Find the earliest available slot within the next 3 hours
    emergency_slot = _find_emergency_slot(admin_id)

    # Get clinic phone for call button
    company = db.get_company_info(admin_id)
    clinic_phone = company.get('phone', '') if company else ''

    # Build the response text
    intros = {
        'en': "\U0001f6a8 **This sounds like an emergency.** Here\u2019s what to do right now while we find you the earliest slot:",
        'ar': "\U0001f6a8 **\u0647\u0630\u0627 \u064a\u0628\u062f\u0648 \u0643\u062d\u0627\u0644\u0629 \u0637\u0648\u0627\u0631\u0626.** \u0625\u0644\u064a\u0643 \u0645\u0627 \u064a\u062c\u0628 \u0641\u0639\u0644\u0647 \u0627\u0644\u0622\u0646 \u0623\u062b\u0646\u0627\u0621 \u0627\u0644\u0628\u062d\u062b \u0639\u0646 \u0623\u0642\u0631\u0628 \u0645\u0648\u0639\u062f:",
        'ur': "\U0001f6a8 **\u06cc\u06c1 \u0627\u06cc\u0645\u0631\u062c\u0646\u0633\u06cc \u0644\u06af\u062a\u06cc \u06c1\u06d2\u06d4** \u0627\u0628\u06be\u06cc \u06cc\u06c1 \u06a9\u0631\u06cc\u06ba \u062c\u0628 \u062a\u06a9 \u06c1\u0645 \u0622\u067e \u06a9\u06d2 \u0644\u06cc\u06d2 \u0642\u0631\u06cc\u0628 \u062a\u0631\u06cc\u0646 \u0648\u0642\u062a \u062a\u0644\u0627\u0634 \u06a9\u0631\u062a\u06d2 \u06c1\u06cc\u06ba:",
        'tl': "\U0001f6a8 **Mukhang emergency ito.** Narito ang dapat gawin habang hinahanap namin ang pinakamaagang slot:",
    }
    intro = intros.get(lang, intros['en'])
    response_parts = [intro, "", first_aid, ""]

    ui_options = None
    if emergency_slot:
        slot_msgs = {
            'en': (
                f"**Earliest emergency slot available:** {emergency_slot['date']} "
                f"at {emergency_slot['time']} with Dr. {emergency_slot['doctor_name']}"
                "\n\nWould you like to book this slot immediately?"
            ),
            'ar': (
                f"**\u0623\u0642\u0631\u0628 \u0645\u0648\u0639\u062f \u0637\u0648\u0627\u0631\u0626 \u0645\u062a\u0627\u062d:** {emergency_slot['date']} "
                f"\u0627\u0644\u0633\u0627\u0639\u0629 {emergency_slot['time']} \u0645\u0639 \u062f. {emergency_slot['doctor_name']}"
                "\n\n\u0647\u0644 \u062a\u0631\u064a\u062f \u062d\u062c\u0632 \u0647\u0630\u0627 \u0627\u0644\u0645\u0648\u0639\u062f \u0641\u0648\u0631\u0627\u064b\u061f"
            ),
            'ur': (
                f"**\u0642\u0631\u06cc\u0628 \u062a\u0631\u06cc\u0646 \u0627\u06cc\u0645\u0631\u062c\u0646\u0633\u06cc \u0633\u0644\u0627\u0679:** {emergency_slot['date']} "
                f"\u0628\u062c\u06d2 {emergency_slot['time']} \u0688\u0627\u06a9\u0679\u0631 {emergency_slot['doctor_name']} \u06a9\u06d2 \u0633\u0627\u062a\u06be"
                "\n\n\u06a9\u06cc\u0627 \u0622\u067e \u06cc\u06c1 \u0633\u0644\u0627\u0679 \u0641\u0648\u0631\u06cc \u0628\u06a9 \u06a9\u0631\u0646\u0627 \u0686\u0627\u06c1\u06cc\u06ba\u06af\u06d2\u061f"
            ),
            'tl': (
                f"**Pinakamaagang emergency slot:** {emergency_slot['date']} "
                f"sa {emergency_slot['time']} kasama si Dr. {emergency_slot['doctor_name']}"
                "\n\nGusto mo bang i-book ito agad?"
            ),
        }
        response_parts.append(slot_msgs.get(lang, slot_msgs['en']))
        ui_options = {
            "type": "emergency_slot",
            "slot": emergency_slot,
            "show_call_button": True,
            "clinic_phone": clinic_phone,
        }
    else:
        no_slot_msgs = {
            'en': "**We have no emergency slots available right now.** Please call us directly or go to the nearest emergency dental clinic.",
            'ar': "**\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0648\u0627\u0639\u064a\u062f \u0637\u0648\u0627\u0631\u0626 \u0645\u062a\u0627\u062d\u0629 \u062d\u0627\u0644\u064a\u0627\u064b.** \u064a\u0631\u062c\u0649 \u0627\u0644\u0627\u062a\u0635\u0627\u0644 \u0628\u0646\u0627 \u0645\u0628\u0627\u0634\u0631\u0629 \u0623\u0648 \u0627\u0644\u062a\u0648\u062c\u0647 \u0644\u0623\u0642\u0631\u0628 \u0639\u064a\u0627\u062f\u0629 \u0637\u0648\u0627\u0631\u0626 \u0623\u0633\u0646\u0627\u0646.",
            'ur': "**\u0627\u0633 \u0648\u0642\u062a \u06a9\u0648\u0626\u06cc \u0627\u06cc\u0645\u0631\u062c\u0646\u0633\u06cc \u0633\u0644\u0627\u0679 \u062f\u0633\u062a\u06cc\u0627\u0628 \u0646\u06c1\u06cc\u06ba\u06d4** \u0628\u0631\u0627\u06c1 \u06a9\u0631\u0645 \u06c1\u0645\u06cc\u06ba \u0628\u0631\u0627\u06c1 \u0631\u0627\u0633\u062a \u06a9\u0627\u0644 \u06a9\u0631\u06cc\u06ba \u06cc\u0627 \u0642\u0631\u06cc\u0628\u06cc \u0627\u06cc\u0645\u0631\u062c\u0646\u0633\u06cc \u0688\u06cc\u0646\u0679\u0644 \u06a9\u0644\u06cc\u0646\u06a9 \u062c\u0627\u0626\u06cc\u06ba\u06d4",
            'tl': "**Walang available na emergency slot ngayon.** Mangyaring tumawag sa amin o pumunta sa pinakamalapit na emergency dental clinic.",
        }
        response_parts.append(no_slot_msgs.get(lang, no_slot_msgs['en']))
        ui_options = {
            "type": "emergency_no_slots",
            "show_call_button": True,
            "clinic_phone": clinic_phone,
        }

    # Create a dashboard alert for clinic staff
    alert = {
        "type": "emergency",
        "patient_name": session_data.get("name", "Unknown Patient"),
        "description": message[:200],
        "keywords": matched,
        "slot_offered": emergency_slot,
        "created_at": datetime.now().isoformat(),
    }

    # Persist the alert
    _save_emergency_alert(admin_id, alert)

    return {
        "response": "\n".join(response_parts),
        "is_emergency": True,
        "first_aid": first_aid,
        "alert": alert,
        "ui_options": ui_options,
    }


# ======================================================================
#  Internal helpers
# ======================================================================

def _find_emergency_slot(admin_id):
    """Find the earliest available appointment slot within the next 3 hours.

    Iterates over all active doctors for the given admin, generates their
    time slots for today, and returns the soonest unbooked one that falls
    between *now* and *now + 3 hours*.

    Returns:
        dict with date, time, doctor_id, doctor_name -- or None.
    """
    import database as db

    now = datetime.now()
    cutoff = now + timedelta(hours=3)
    today = now.strftime("%Y-%m-%d")

    doctors = db.get_doctors(admin_id)
    active_doctors = [d for d in doctors if d.get("status") == "active"]

    earliest = None

    for doctor in active_doctors:
        # Retrieve already-booked time labels for today
        booked = db.get_booked_times(doctor["id"], today)
        booked_times = set(booked) if booked else set()

        start_time = doctor.get("start_time", "09:00 AM")
        end_time = doctor.get("end_time", "05:00 PM")
        appt_length = doctor.get("appointment_length", 30)

        try:
            start_dt = datetime.strptime(f"{today} {start_time}", "%Y-%m-%d %I:%M %p")
            end_dt = datetime.strptime(f"{today} {end_time}", "%Y-%m-%d %I:%M %p")
        except ValueError:
            continue

        current = start_dt
        while current + timedelta(minutes=appt_length) <= end_dt:
            slot_time = current.strftime("%I:%M %p").lstrip("0")
            slot_end = (current + timedelta(minutes=appt_length)).strftime("%I:%M %p").lstrip("0")
            slot_label = f"{slot_time} - {slot_end}"

            if current > now and current < cutoff:
                if slot_label not in booked_times and slot_time not in booked_times:
                    candidate = {
                        "date": today,
                        "time": slot_label,
                        "doctor_id": doctor["id"],
                        "doctor_name": doctor["name"],
                        "_dt": current,
                    }
                    if earliest is None or current < earliest["_dt"]:
                        earliest = candidate

            current += timedelta(minutes=appt_length)

    if earliest:
        del earliest["_dt"]  # Remove non-serializable helper field
    return earliest


def _save_emergency_alert(admin_id, alert):
    """Persist an emergency alert to the database for the staff dashboard.

    Creates the ``emergency_alerts`` table on first use (idempotent).
    """
    import database as db

    conn = db.get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS emergency_alerts (
                id SERIAL PRIMARY KEY,
                admin_id INTEGER,
                patient_name TEXT,
                description TEXT,
                keywords_matched TEXT,
                slot_offered TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO emergency_alerts "
            "(admin_id, patient_name, description, keywords_matched, "
            "slot_offered, status, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                admin_id,
                alert["patient_name"],
                alert["description"],
                json.dumps(alert["keywords"]),
                json.dumps(alert.get("slot_offered")),
                "active",
                alert["created_at"],
            ),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to save emergency alert: %s", e)
    finally:
        conn.close()


# ======================================================================
#  4. API route helpers (to be registered in app.py)
# ======================================================================
#
# Add the following routes to app.py to expose emergency alerts on the
# staff dashboard:
#
#   GET  /api/emergency-alerts              - List active emergency alerts
#   POST /api/emergency-alerts/<id>/acknowledge - Mark an alert as acknowledged
#
# Example integration in app.py:
#
#   from emergency_handler import get_emergency_alerts, acknowledge_alert
#
#   @app.route("/api/emergency-alerts", methods=["GET"])
#   def api_emergency_alerts():
#       token = request.headers.get("Authorization", "").replace("Bearer ", "")
#       user = db.get_user_by_token(token)
#       if not user:
#           return jsonify({"error": "Unauthorized"}), 401
#       admin_id = get_effective_admin_id(user)
#       return jsonify(get_emergency_alerts(admin_id))
#
#   @app.route("/api/emergency-alerts/<int:alert_id>/acknowledge", methods=["POST"])
#   def api_acknowledge_alert(alert_id):
#       token = request.headers.get("Authorization", "").replace("Bearer ", "")
#       user = db.get_user_by_token(token)
#       if not user:
#           return jsonify({"error": "Unauthorized"}), 401
#       return jsonify(acknowledge_alert(alert_id))


def get_emergency_alerts(admin_id, status="active"):
    """Retrieve emergency alerts for a clinic (used by dashboard API).

    Args:
        admin_id: The clinic admin's user ID.
        status:   Filter by status ('active', 'acknowledged', or None for all).

    Returns:
        list[dict]: Alert rows.
    """
    import database as db

    conn = db.get_db()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM emergency_alerts WHERE admin_id = %s AND status = %s "
                "ORDER BY created_at DESC",
                (admin_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM emergency_alerts WHERE admin_id = %s "
                "ORDER BY created_at DESC",
                (admin_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def acknowledge_alert(alert_id):
    """Mark an emergency alert as acknowledged by staff.

    Args:
        alert_id: The integer ID of the alert row.

    Returns:
        dict: {"ok": True} on success, {"error": str} on failure.
    """
    import database as db

    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE emergency_alerts SET status = 'acknowledged' WHERE id = %s",
            (alert_id,),
        )
        conn.commit()
        return {"ok": True}
    except Exception as e:
        logger.error("Failed to acknowledge alert %s: %s", alert_id, e)
        return {"error": str(e)}
    finally:
        conn.close()
