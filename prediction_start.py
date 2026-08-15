"""Railway entrypoint for the standalone prediction dashboard service."""
from prediction_model_bootstrap import ensure_models


def main() -> None:
    ensure_models()
    import prediction_dashboard  # imported after models exist

    port = int(__import__("os").getenv("PORT", "8080"))
    server = prediction_dashboard.ThreadingHTTPServer(("0.0.0.0", port), prediction_dashboard.Handler)
    print(f"Prediction dashboard listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
