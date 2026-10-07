import psycopg2
from config import DB_CONFIG

def connect():
    return psycopg2.connect(**DB_CONFIG)

def insert_game(conn, game_obj):
    with conn.cursor() as cur:
        try:
            # Safely derive sport title
            sport_key = game_obj["sport_key"]
            title = sport_key.split("_")[-1].upper() if "_" in sport_key else sport_key.upper()

            cur.execute("""
                INSERT INTO sports (key, title)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET title = EXCLUDED.title
                RETURNING id
            """, (sport_key, title))
            sport_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO games (id, sport_id, game_date, home_team, away_team, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET sport_id = EXCLUDED.sport_id,
                    game_date = EXCLUDED.game_date,
                    home_team = EXCLUDED.home_team,
                    away_team = EXCLUDED.away_team,
                    status = EXCLUDED.status,
                    updated_at = NOW()
            """, (
                game_obj["id"], sport_id, game_obj["game_date"],
                game_obj["home_team"], game_obj["away_team"], game_obj["status"]
            ))

            conn.commit()
            return game_obj["id"]

        except Exception as e:
            print("❌ insert_game error:", e)
            print("Game object:", game_obj)
            raise


def insert_odds(conn, game_id, odds_list):
    with conn.cursor() as cur:
        for odds in odds_list:
            cur.execute("""
                INSERT INTO odds (
                    game_id, sportsbook, market, side,
                    price, decimal_price, implied_prob, point,
                    betslip_link, market_link, event_link,
                    fetched_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                game_id,
                odds["sportsbook"], odds["market"], odds["side"],
                odds["price"], odds["decimal_price"],
                odds["implied_prob"], odds["point"],
                odds.get("betslip_link"), odds.get("market_link"), odds.get("event_link")
            ))
        conn.commit()
