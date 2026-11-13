# Answers response fixture with anonymized sample data

ANSWERS_CREATE_RESPONSE = {
    "id": "answer_abc123def456",
    "object": "answer",
    "created": 1761162851,
    "metadata": {},
    "task": "list all products available on the website",
    "result": {
        "json_content": "{\"products\":[{\"id\":\"1\",\"sku\":\"BK001\",\"title\":\"Programming Basics\",\"url\":\"https://example-store.com/products/programming-basics\",\"available\":true},{\"id\":\"2\",\"sku\":\"BK002\",\"title\":\"Data Structures Guide\",\"url\":\"https://example-store.com/products/data-structures-guide\",\"available\":true},{\"id\":\"3\",\"sku\":\"EL001\",\"title\":\"Wireless Headphones\",\"url\":\"https://example-store.com/products/wireless-headphones\",\"available\":true},{\"id\":\"4\",\"sku\":\"EL002\",\"title\":\"Smartphone Case\",\"url\":\"https://example-store.com/products/smartphone-case\",\"available\":true},{\"id\":\"5\",\"sku\":\"BK003\",\"title\":\"Machine Learning Handbook\",\"url\":\"https://example-store.com/products/machine-learning-handbook\",\"available\":true},{\"id\":\"6\",\"sku\":\"HM001\",\"title\":\"Coffee Maker\",\"url\":\"https://example-store.com/products/coffee-maker\",\"available\":true},{\"id\":\"7\",\"sku\":\"BK004\",\"title\":\"Web Development Guide\",\"url\":\"https://example-store.com/products/web-development-guide\",\"available\":true},{\"id\":\"8\",\"sku\":\"EL003\",\"title\":\"USB Cable Set\",\"url\":\"https://example-store.com/products/usb-cable-set\",\"available\":true},{\"id\":\"9\",\"sku\":\"SP001\",\"title\":\"Running Shoes\",\"url\":\"https://example-store.com/products/running-shoes\",\"available\":true},{\"id\":\"10\",\"sku\":\"BK005\",\"title\":\"Database Design\",\"url\":\"https://example-store.com/products/database-design\",\"available\":true}]}",
        "json_hosted_url": "https://olostep-storage.s3.us-east-1.amazonaws.com/answer_abc123def456.json",
        "sources": [
            "https://example-store.com/collections/books",
            "https://example-store.com/collections/electronics",
            "https://example-store.com/collections/home",
            "https://example-store.com/collections/sports",
            "https://example-store.com/collections/all"
        ]
    }
}
