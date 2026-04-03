"""
Runtime module for the sklearn-trained intent classifier.
Loads the trained pipeline from intent_classifier.pkl and provides
a classify() function matching the existing intent_classifier interface.
"""
import os
import pickle

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "intent_classifier.pkl")
_model = None
_ready = False


def _load():
    global _model, _ready
    if not os.path.exists(_MODEL_PATH):
        print("[sklearn_classifier] Model file not found, run train_sklearn_classifier.py first")
        return False
    with open(_MODEL_PATH, "rb") as f:
        _model = pickle.load(f)
    _ready = True
    print("[sklearn_classifier] Loaded intent classifier")
    return True


def classify(text):
    """
    Classify text into one of the trained dental intents.
    Returns: (intent_name, confidence)
    """
    if not _ready:
        if not _load():
            return None, 0.0
    try:
        intent = _model.predict([text])[0]
        proba = _model.predict_proba([text])[0]
        confidence = max(proba)
        return intent, float(confidence)
    except Exception as e:
        print(f"[sklearn_classifier] Error: {e}")
        return None, 0.0


# Auto-load on import
_load()
