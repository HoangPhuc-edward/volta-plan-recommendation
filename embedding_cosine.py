import numpy as np
from sentence_transformers import SentenceTransformer


_model_cache = {}


def get_embedding_model(model_name: str, device: str = "cpu"):
    cache_key = f"{model_name}:{device}"

    if cache_key not in _model_cache:
        _model_cache[cache_key] = SentenceTransformer(model_name, device=device)

    return _model_cache[cache_key]


def cosine_similarity(vec_a, vec_b):
    vec_a = np.asarray(vec_a)
    vec_b = np.asarray(vec_b)

    denominator = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)

    if denominator == 0:
        return 0.0

    return float(np.dot(vec_a, vec_b) / denominator)


def calculate_text_cosine_similarity(
    text_a: str,
    text_b: str,
    model_name: str = "Alibaba-NLP/gte-modernbert-base",
    device: str = "cpu"
):
    model = get_embedding_model(model_name, device=device)

    embeddings = model.encode(
        [text_a, text_b],
        normalize_embeddings=True
    )

    return cosine_similarity(embeddings[0], embeddings[1])


def is_recommended_text_better_than_seed(
    user_text: str,
    recommended_plan_text: str,
    seed_plan_text: str,
    model_name: str = "Alibaba-NLP/gte-modernbert-base",
    device: str = "cpu"
):
    recommended_similarity = calculate_text_cosine_similarity(
        user_text,
        recommended_plan_text,
        model_name=model_name,
        device=device
    )

    seed_similarity = calculate_text_cosine_similarity(
        user_text,
        seed_plan_text,
        model_name=model_name,
        device=device
    )

    return {
        "recommended_similarity": recommended_similarity,
        "seed_similarity": seed_similarity,
        "is_better": recommended_similarity >= seed_similarity
    }