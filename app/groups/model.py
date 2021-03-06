from app.configurations.database import db
from app.users.model import UserModel
from app.accounts.model import AccountModel
from app.journal.model import JournalModel
from app.transactions.model import TransactionModel, TransactionType
from app.expenses.model import ExpenseModel

from datetime import datetime


class GroupModel(db.Model):
    __tablename__ = "groups"

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String, nullable=False)
    access_code = db.Column(db.String, nullable=False)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey(
            ("users.id"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
    )

    members_list = db.relationship(
        "UserModel", backref="groups_list", secondary="accounts"
    )

    entries_list = db.relationship("JournalModel", backref="group")

    categories_list = db.relationship("CategoryModel", backref="group")

    def __repr__(self):
        return f"<Grupo {self.name} -- Feito por id->{self.created_by}>"

    def is_member(self, user_id: int) -> int:
        members_id = [member.id for member in self.members_list]
        return user_id in members_id

    def are_members(self, users_id: list) -> bool:
        return all([self.is_member(user_id) for user_id in users_id])

    def create_payment(self, sender_id: int, receiver_id: int, amount: float):
        if not self.are_members([sender_id, receiver_id]):
            raise ValueError("Not all users are group members.")

        sender_account = AccountModel.query.filter_by(
            user_id=sender_id,
            group_id=self.id,
        ).first()

        receiver_account = AccountModel.query.filter_by(
            user_id=receiver_id,
            group_id=self.id,
        ).first()

        payment_entry: JournalModel = JournalModel.create(
            name="Pagamento",
            amount=amount,
            group_id=self.id,
            created_by=sender_id,
            created_at=datetime.now(),
        )

        sender_transaction: TransactionModel = TransactionModel.create(
            amount=amount,
            type=TransactionType.debit,
            entry_id=payment_entry.id,
            target_account=sender_account.id,
        )

        receiver_transaction: TransactionModel = TransactionModel.create(
            amount=amount,
            type=TransactionType.credit,
            entry_id=payment_entry.id,
            target_account=receiver_account.id,
        )

        return {
            "entry": payment_entry,
            "transactions": {
                "credit": sender_transaction,
                "debit": receiver_transaction,
            },
        }

    def create_expense(
        self,
        name: str,
        amount: id,
        created_by: id,
        splitted: dict,
        category_id: int = None,
        description: str = "",
    ):
        payers = splitted["payers"]
        benefited = splitted["benefited"]

        payers_id = [payer["payer_id"] for payer in payers]
        benefited_id = [benefiter["benefited_id"] for benefiter in benefited]

        if not self.are_members(payers_id + benefited_id):
            raise ValueError("Not all users are group members.")

        payers_amount = [payer["paid_amount"] for payer in payers]
        benefited_amount = [benefiter["benefited_amount"] for benefiter in benefited]

        from functools import reduce

        payers_total = reduce(lambda acc, cur: acc + cur, payers_amount)
        benefited_total = reduce(lambda acc, cur: acc + cur, benefited_amount)

        if not amount == benefited_total == payers_total:
            raise ValueError("Amount Splitted is diferent from Expense amount.")

        expense_entry = JournalModel.create(
            name=name,
            amount=amount,
            group_id=self.id,
            created_by=created_by,
            created_at=datetime.now(),
        )

        for payer in payers:
            payer_account = AccountModel.query.filter_by(
                user_id=payer["payer_id"], group_id=self.id
            ).first()

            TransactionModel.create(
                amount=payer["paid_amount"],
                type=TransactionType.debit,
                entry_id=expense_entry.id,
                target_account=payer_account.id,
            )

        for benefiter in benefited:
            benefiter_account = AccountModel.query.filter_by(
                user_id=benefiter["benefited_id"], group_id=self.id
            ).first()

            TransactionModel.create(
                amount=benefiter["benefited_amount"],
                type=TransactionType.credit,
                entry_id=expense_entry.id,
                target_account=benefiter_account.id,
            )

        expense = ExpenseModel.create(
            description=description,
            journal_id=expense_entry.id,
            category_id=category_id,
        )

        return expense_entry

    def list_all_transactions(self):
        entries = JournalModel.query.filter_by(group_id=self.id).all()

        from app.transactions.services import transaction_serializer

        serialized_entries = [transaction_serializer(entry) for entry in entries]

        return serialized_entries

    def get_balance(self):
        def get_member_transactions(member: UserModel):
            return (
                member.id,
                [
                    transaction
                    for transaction in self.transactions_list
                    if transaction.target_user.first().id == member.id
                ],
            )

        members_transactions = [
            get_member_transactions(member) for member in self.members_list
        ]

        from .services import create_member_balance

        members_balance = [
            create_member_balance(*member_transaction)
            for member_transaction in members_transactions
        ]

        return members_balance

    def suggested_payments(self):
        balances = self.get_balance()

        suggestions = []

        while len(balances) > 1:
            saldos = [balance.get("user_saldo") for balance in balances]
            owed_amount = min(saldos)
            ower = next(
                balance["user_id"]
                for balance in balances
                if balance["user_saldo"] == owed_amount
            )
            lend_amount = max(saldos)
            lender = next(
                balance["user_id"]
                for balance in balances
                if balance["user_saldo"] == lend_amount
            )

            if owed_amount != 0:
                suggestions.append(
                    {"payer": ower, "receiver": lender, "amount": abs(owed_amount)}
                )

            new_balance = []

            for balance in balances:
                if balance["user_id"] == ower:
                    continue
                elif balance["user_id"] == lender:
                    new_balance.append(
                        {"user_id": lender, "user_saldo": (lend_amount - owed_amount)}
                    )
                else:
                    new_balance.append(balance)

            balances = new_balance

        return {"suggedted_payments": suggestions}
