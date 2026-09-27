from flask import Flask, request, jsonify
import database

app = Flask(__name__)
database.init_db()

# ---------- Transactions ----------

@app.route("/transactions", methods=["GET"])
def list_transactions():
    month = request.args.get("month")
    if month:
        return jsonify(database.get_transactions_by_month(month))
    return jsonify(database.get_all_transactions())

@app.route("/transactions", methods=["POST"])
def create_transaction():
    data = request.get_json()
    database.add_transaction(
        data["type"], data["category"], data["amount"],
        data.get("note", ""), data.get("date"), data.get("source")
    )
    return jsonify({"status": "ok"}), 201

@app.route("/transactions/<int:t_id>", methods=["DELETE"])
def remove_transaction(t_id):
    database.delete_transaction(t_id)
    return jsonify({"status": "deleted"})

@app.route("/months", methods=["GET"])
def list_months():
    return jsonify(database.get_available_months())

# ---------- Money sources ----------

@app.route("/sources", methods=["GET"])
def list_sources():
    month = request.args.get("month")
    return jsonify(database.get_sources_by_month(month))

@app.route("/sources", methods=["POST"])
def upsert_source():
    data = request.get_json()
    database.set_source_amount(data["month"], data["source"], data["amount"])
    return jsonify({"status": "ok"})

@app.route("/sources", methods=["DELETE"])
def remove_source():
    data = request.get_json()
    database.delete_source(data["month"], data["source"])
    return jsonify({"status": "deleted"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)