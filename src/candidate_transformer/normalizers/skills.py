"""Skills normalizer — canonical taxonomy via synonym/alias dictionary.

Rules:
- Canonicalize via a synonym dict (``"js" → "JavaScript"``, ``"react.js" → "React"``).
- Casing normalization to title-case for unknown skills.
- Unknown skill strings pass through as-is (still useful) but get flagged as
  ``unverified`` so the merger can apply a lower base confidence.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Synonym / alias dictionary — maps lowercase alias → canonical name.
_SYNONYMS: dict[str, str] = {
    # JavaScript ecosystem
    "js": "JavaScript",
    "javascript": "JavaScript",
    "es6": "JavaScript",
    "ecmascript": "JavaScript",
    "react.js": "React",
    "reactjs": "React",
    "react": "React",
    "react.js": "React",
    "vue.js": "Vue",
    "vuejs": "Vue",
    "vue": "Vue",
    "angular.js": "Angular",
    "angularjs": "Angular",
    "angular": "Angular",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "node": "Node.js",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "express.js": "Express",
    "expressjs": "Express",
    # Python ecosystem
    "python": "Python",
    "python3": "Python",
    "py": "Python",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "tensorflow": "TensorFlow",
    "tf": "TensorFlow",
    "pytorch": "PyTorch",
    "torch": "PyTorch",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "pandas": "Pandas",
    "numpy": "NumPy",
    # Databases
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "psql": "PostgreSQL",
    "mysql": "MySQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "sql": "SQL",
    "nosql": "NoSQL",
    "sqlite": "SQLite",
    # Cloud / DevOps
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "azure": "Azure",
    "microsoft azure": "Azure",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "terraform": "Terraform",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "ci / cd": "CI/CD",
    "jenkins": "Jenkins",
    # Languages
    "golang": "Go",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "ruby": "Ruby",
    "scala": "Scala",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "r": "R",
    "php": "PHP",
    # Data / ML
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "dl": "Deep Learning",
    "nlp": "NLP",
    "natural language processing": "NLP",
    "computer vision": "Computer Vision",
    "cv": "Computer Vision",
    "data science": "Data Science",
    "spark": "Apache Spark",
    "apache spark": "Apache Spark",
    "hadoop": "Hadoop",
    "mlops": "MLOps",
    # Misc
    "git": "Git",
    "github": "GitHub",
    "linux": "Linux",
    "rest": "REST APIs",
    "rest api": "REST APIs",
    "rest apis": "REST APIs",
    "graphql": "GraphQL",
    "html": "HTML",
    "css": "CSS",
}


def normalize_skill(raw: str) -> tuple[str, bool]:
    """Normalise *raw* skill string to canonical name.

    Returns:
        ``(canonical_name, is_verified)`` — ``is_verified`` is ``True`` if the
        skill was found in the synonym dictionary, ``False`` if it's an unknown
        pass-through (lower confidence applies).
    """
    if not raw or not raw.strip():
        return raw, False

    key = raw.strip().lower()

    if key in _SYNONYMS:
        return _SYNONYMS[key], True

    # Unknown skill: title-case and pass through.
    canonical = raw.strip().title()
    logger.debug("Skill not in taxonomy, passing through: %r → %r", raw, canonical)
    return canonical, False
