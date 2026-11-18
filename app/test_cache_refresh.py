
from app.db.session import SessionLocal
from app.services.cache_refresh_service import refresh_lumina_cache


def main():
    db = SessionLocal()

    try:
        print("\n===================================")
        print(" LUMINA CACHE REFRESH TEST")
        print("===================================\n")

        result = refresh_lumina_cache(db)

        print("\n========== REFRESH RESULT ==========")
        print(result)
        print("====================================\n")

    except Exception as e:
        print("\nCACHE REFRESH FAILED:")
        print(str(e))

    finally:
        db.close()
        print("Database session closed.")


if __name__ == "__main__":
    main()
