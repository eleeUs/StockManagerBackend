"""
movements/services.py

The service layer is the ONLY place where stock mutation logic lives.
Views, serializers, and signals must never modify stock directly.

Concurrency strategy:
- Every operation that reads then writes stock uses select_for_update()
  inside transaction.atomic(). This serializes concurrent writes to the
  same (product, branch) stock row at the database level.
- For transfers involving two branches, locks are always acquired in
  ascending branch_id order to prevent deadlocks when two transfers
  try to lock the same two branches in opposite order simultaneously.
- The DB-level CheckConstraint on Stock.quantity is the final safety net,
  but InsufficientStockError should always fire first at the app level.
"""
import logging
from decimal import Decimal

from django.db import transaction

from apps.stock.models import Stock
from apps.movements.models import StockMovement, MovementType, MovementStatus
from core.exceptions import (
    InsufficientStockError,
    InvalidMovementError,
    TransferAlreadyConfirmedError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lock_stock(product_id, branch_id) -> Stock:
    """
    Acquire a row-level lock on the stock row for (product, branch).
    MUST be called inside transaction.atomic().

    Returns the locked Stock instance.
    Raises InvalidMovementError if no stock row exists for this combination
    (which means the product has never been stocked at this branch).
    """
    try:
        return Stock.objects.select_for_update().get(
            product_id=product_id,
            branch_id=branch_id,
        )
    except Stock.DoesNotExist:
        raise InvalidMovementError(
            "No stock record found for this product at the specified branch. "
            "A formal entry (ingreso) must be created first."
        )


def _get_or_create_and_lock_stock(product_id, branch_id) -> Stock:
    """
    Get or create the stock row, then lock it.
    Used for INGRESO and DEVOLUCION which can legitimately be the first
    movement for a (product, branch) pair.

    The get_or_create handles the race condition for first-time creation:
    Django catches the IntegrityError from a concurrent INSERT and retries
    the GET, so at most one row is ever created per (product, branch).
    The subsequent select_for_update serializes the update.
    """
    Stock.objects.get_or_create(
        product_id=product_id,
        branch_id=branch_id,
        defaults={"quantity": Decimal("0.000")},
    )
    return Stock.objects.select_for_update().get(
        product_id=product_id,
        branch_id=branch_id,
    )


def _lock_two_stocks(product_id, branch_id_a, branch_id_b):
    """
    Acquire row-level locks on two stock rows in a deterministic order
    (ascending branch_id) to prevent deadlocks.

    Scenario without ordered locking:
      T1 locks branch 1, waits for branch 2
      T2 locks branch 2, waits for branch 1  → deadlock

    Scenario with ordered locking:
      Both T1 and T2 try to lock branch 1 first → one waits, no deadlock.

    Returns (stock_a, stock_b) in the ORIGINAL order (not the lock order),
    so callers can use them by their semantic role (source, destination).
    """
    # Sort IDs to guarantee consistent lock order
    id_low, id_high = sorted([branch_id_a, branch_id_b])

    locked = {
        s.branch_id: s
        for s in Stock.objects.select_for_update().filter(
            product_id=product_id,
            branch_id__in=[id_low, id_high],
        )
    }

    stock_a = locked.get(branch_id_a)
    stock_b = locked.get(branch_id_b)

    if stock_a is None:
        raise InvalidMovementError(
            "No stock record found for this product at the source branch."
        )
    if stock_b is None:
        # Destination may not have stock yet — create it then re-lock
        Stock.objects.get_or_create(
            product_id=product_id,
            branch_id=branch_id_b,
            defaults={"quantity": Decimal("0.000")},
        )
        # Re-acquire both locks after creation (consistent order preserved)
        locked = {
            s.branch_id: s
            for s in Stock.objects.select_for_update().filter(
                product_id=product_id,
                branch_id__in=[id_low, id_high],
            )
        }
        stock_a = locked[branch_id_a]
        stock_b = locked[branch_id_b]

    return stock_a, stock_b


# ---------------------------------------------------------------------------
# Public service methods
# ---------------------------------------------------------------------------

class StockMovementService:
    """
    All methods are @classmethod to allow easy mocking in tests
    without requiring instantiation.
    """

    @classmethod
    def ingreso(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        entry_date,
        user,
        notes: str = "",
        supplier_id: int = None,
    ) -> StockMovement:
        """
        INGRESO — Adds stock to a branch.
        Allowed: Admin only (enforced at the view level).
        Stock effect: +quantity at destination branch.
        Creates the stock row if it does not yet exist.
        supplier_id is optional — not every entry has a supplier on file
        (BUSINESS_RULES §10). The DB constraint
        movement_supplier_only_for_ingreso guards against it ever being
        set on any other movement type.
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        with transaction.atomic():
            stock = _get_or_create_and_lock_stock(product_id, branch_id)
            stock.quantity += quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.INGRESO,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                destination_branch_id=branch_id,
                quantity=quantity,
                entry_date=entry_date,
                supplier_id=supplier_id,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "INGRESO: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def venta(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        VENTA — Sells stock from a branch.
        Allowed: Admin or Seller (seller restricted to their own branch,
                 enforced at the view level).
        Stock effect: -quantity at source branch.
        Raises InsufficientStockError if stock < quantity.
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        with transaction.atomic():
            stock = _lock_stock(product_id, branch_id)

            if stock.quantity < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock at this branch. "
                    f"Available: {stock.quantity}, requested: {quantity}."
                )

            stock.quantity -= quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.VENTA,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                source_branch_id=branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "VENTA: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def crear_transferencia(
        cls,
        *,
        product_id: int,
        source_branch_id: int,
        destination_branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        TRANSFERENCIA (step 1 of 2) — Creates a pending transfer.
        Allowed: Admin only.

        Stock effect on creation:
          -quantity at source branch immediately (reserved).
          +quantity at destination branch ONLY on confirmation.

        The source stock is decremented on creation so it cannot be
        sold or moved by other operations while the transfer is pending.
        (BUSINESS_RULES §3.3)
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")
        if source_branch_id == destination_branch_id:
            raise InvalidMovementError(
                "Source and destination branches must be different."
            )

        with transaction.atomic():
            # Lock source only on creation — destination is locked on confirmation
            source_stock = _lock_stock(product_id, source_branch_id)

            if source_stock.quantity < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock at source branch. "
                    f"Available: {source_stock.quantity}, requested: {quantity}."
                )

            # Decrement source immediately — quantity is "in transit"
            source_stock.quantity -= quantity
            source_stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.TRANSFERENCIA,
                status=MovementStatus.PENDING,
                product_id=product_id,
                source_branch_id=source_branch_id,
                destination_branch_id=destination_branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "TRANSFERENCIA PENDING: product=%s src=%s dst=%s qty=%s by=%s",
            product_id, source_branch_id, destination_branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def confirmar_transferencia(
        cls,
        *,
        movement_id: int,
        user,
    ) -> StockMovement:
        """
        TRANSFERENCIA (step 2 of 2) — Confirms a pending transfer.
        Allowed: Admin only.

        Stock effect: +quantity at destination branch.
        The source was already decremented on creation.
        """
        with transaction.atomic():
            # Lock the movement row itself to prevent concurrent confirmations
            try:
                movement = (
                    StockMovement.objects
                    .select_for_update()
                    .select_related("product")
                    .get(pk=movement_id, movement_type=MovementType.TRANSFERENCIA)
                )
            except StockMovement.DoesNotExist:
                raise InvalidMovementError("Transfer movement not found.")

            if movement.is_confirmed:
                raise TransferAlreadyConfirmedError(
                    "This transfer has already been confirmed."
                )
            if movement.is_cancelled:
                raise InvalidMovementError(
                    "A cancelled transfer cannot be confirmed."
                )

            # Lock and update destination stock
            dest_stock = _get_or_create_and_lock_stock(
                movement.product_id,
                movement.destination_branch_id,
            )
            dest_stock.quantity += movement.quantity
            dest_stock.save(update_fields=["quantity", "updated_at"])

            movement.status = MovementStatus.CONFIRMED
            movement.save(update_fields=["status"])

        logger.info(
            "TRANSFERENCIA CONFIRMED: movement=%s by=%s",
            movement_id, user.email,
        )
        return movement

    @classmethod
    def cancelar_transferencia(
        cls,
        *,
        movement_id: int,
        user,
    ) -> StockMovement:
        """
        TRANSFERENCIA — Cancels a pending transfer.
        Allowed: Admin only.

        Stock effect: +quantity restored to source branch.
        Cannot cancel a confirmed transfer — create a reversal instead.
        (BUSINESS_RULES §5)
        """
        with transaction.atomic():
            try:
                movement = (
                    StockMovement.objects
                    .select_for_update()
                    .get(pk=movement_id, movement_type=MovementType.TRANSFERENCIA)
                )
            except StockMovement.DoesNotExist:
                raise InvalidMovementError("Transfer movement not found.")

            if movement.is_confirmed:
                raise TransferAlreadyConfirmedError(
                    "A confirmed transfer cannot be cancelled. "
                    "Create a reversal movement instead."
                )
            if movement.is_cancelled:
                raise InvalidMovementError(
                    "This transfer is already cancelled."
                )

            # Restore source stock
            source_stock = _get_or_create_and_lock_stock(
                movement.product_id,
                movement.source_branch_id,
            )
            source_stock.quantity += movement.quantity
            source_stock.save(update_fields=["quantity", "updated_at"])

            movement.status = MovementStatus.CANCELLED
            movement.save(update_fields=["status"])

        logger.info(
            "TRANSFERENCIA CANCELLED: movement=%s by=%s",
            movement_id, user.email,
        )
        return movement

    @classmethod
    def ajuste(
        cls,
        *,
        product_id: int,
        branch_id: int,
        new_quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        AJUSTE — Sets stock at a branch to an absolute value.
        Allowed: Admin only.

        new_quantity is the target quantity after the adjustment.
        Stores adjustment_previous_quantity for full audit visibility.
        Can set stock to zero. Cannot set below zero.
        (BUSINESS_RULES §3.4)
        """
        if new_quantity < 0:
            raise InvalidMovementError(
                "Adjustment quantity cannot be negative."
            )

        with transaction.atomic():
            stock = _get_or_create_and_lock_stock(product_id, branch_id)
            previous_quantity = stock.quantity

            if new_quantity == previous_quantity:
                raise InvalidMovementError(
                    "New quantity is the same as current stock. No adjustment needed."
                )

            stock.quantity = new_quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.AJUSTE,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                destination_branch_id=branch_id,
                # quantity stores the new absolute value for adjustments
                quantity=new_quantity if new_quantity > 0 else Decimal("0.001"),
                adjustment_previous_quantity=previous_quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "AJUSTE: product=%s branch=%s prev=%s new=%s by=%s",
            product_id, branch_id, previous_quantity, new_quantity, user.email,
        )
        return movement

    @classmethod
    def devolucion(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
        original_movement_id: int = None,
    ) -> StockMovement:
        """
        DEVOLUCION — Returns stock to the branch where it was sold.
        Allowed: Admin only.

        Must go back to the same branch where the original sale occurred.
        (BUSINESS_RULES §3.5)
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        original_movement = None
        if original_movement_id is not None:
            try:
                original_movement = StockMovement.objects.get(
                    pk=original_movement_id,
                    movement_type=MovementType.VENTA,
                    source_branch_id=branch_id,
                )
            except StockMovement.DoesNotExist:
                raise InvalidMovementError(
                    "Referenced movement not found, is not a sale, "
                    "or does not belong to this branch."
                )

            if quantity > original_movement.quantity:
                raise InvalidMovementError(
                    f"Return quantity ({quantity}) exceeds original sale "
                    f"quantity ({original_movement.quantity})."
                )

        with transaction.atomic():
            stock = _get_or_create_and_lock_stock(product_id, branch_id)
            stock.quantity += quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.DEVOLUCION,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                destination_branch_id=branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
                reverses_movement=original_movement,
            )

        logger.info(
            "DEVOLUCION: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def donacion(
        cls,
        *,
        product_id: int,
        branch_id: int,
        quantity: Decimal,
        user,
        notes: str = "",
    ) -> StockMovement:
        """
        DONACION — Removes stock from a branch as a donation.
        Allowed: Admin only.

        Stock effect: -quantity at source branch.
        Raises InsufficientStockError if stock < quantity.
        """
        if quantity <= 0:
            raise InvalidMovementError("Quantity must be greater than zero.")

        with transaction.atomic():
            stock = _lock_stock(product_id, branch_id)

            if stock.quantity < quantity:
                raise InsufficientStockError(
                    f"Insufficient stock at this branch. "
                    f"Available: {stock.quantity}, requested: {quantity}."
                )

            stock.quantity -= quantity
            stock.save(update_fields=["quantity", "updated_at"])

            movement = StockMovement.objects.create(
                movement_type=MovementType.DONACION,
                status=MovementStatus.CONFIRMED,
                product_id=product_id,
                source_branch_id=branch_id,
                quantity=quantity,
                created_by=user,
                notes=notes,
            )

        logger.info(
            "DONACION: product=%s branch=%s qty=%s by=%s",
            product_id, branch_id, quantity, user.email,
        )
        return movement

    @classmethod
    def revertir(cls, *, movement_id: int, user) -> StockMovement:
        """
        REVERSAL — Creates a movement that undoes a confirmed movement.
        Allowed: Admin only (enforced at the view level).

        Dispatches to a type-specific strategy function via REVERSAL_STRATEGIES.
        The strategy pattern avoids a monolithic if/elif block and makes adding
        new movement types in the future a matter of registering one function,
        not modifying the dispatcher.

        Rules (BUSINESS_RULES §5):
        - Only CONFIRMED movements can be reversed.
        - PENDING transfers must be cancelled via cancelar_transferencia,
          not reversed.
        - A movement with an existing reversal cannot be reversed again
          (OneToOne constraint on reverses_movement prevents duplicates at
          the DB level too, but we validate early for a clear error message).
        - Reversal movements themselves cannot be reversed (no chains).
        """
        try:
            movement = (
                StockMovement.objects
                .select_related("product", "source_branch", "destination_branch")
                .get(pk=movement_id)
            )
        except StockMovement.DoesNotExist:
            raise InvalidMovementError(f"Movement #{movement_id} not found.")

        # Guard: pending transfers have their own flow
        if movement.movement_type == MovementType.TRANSFERENCIA and movement.is_pending:
            raise InvalidMovementError(
                "Pending transfers must be cancelled via the cancel endpoint, "
                "not reversed."
            )

        # Guard: only confirmed movements can be reversed
        if not movement.is_confirmed:
            raise InvalidMovementError(
                "Only confirmed movements can be reversed."
            )

        # Guard: reversals cannot be chained
        if movement.movement_type == MovementType.REVERSAL:
            raise InvalidMovementError(
                "Reversal movements cannot themselves be reversed."
            )

        # Guard: already reversed (DB enforces OneToOne but we surface a clear message)
        if StockMovement.objects.filter(reverses_movement_id=movement.pk).exists():
            raise InvalidMovementError(
                f"Movement #{movement_id} has already been reversed."
            )

        strategy = _REVERSAL_STRATEGIES.get(movement.movement_type)
        if strategy is None:
            raise InvalidMovementError(
                f"No reversal strategy is defined for movement type "
                f"'{movement.movement_type}'."
            )

        reversal = strategy(movement, user)

        logger.info(
            "REVERSAL: original_movement=%s type=%s by=%s",
            movement_id, movement.movement_type, user.email,
        )
        return reversal


# ---------------------------------------------------------------------------
# Reversal helpers — private, called only via _REVERSAL_STRATEGIES
# ---------------------------------------------------------------------------

def _create_reversal_record(
    *,
    original: StockMovement,
    user,
    source_branch=None,
    destination_branch=None,
    quantity: Decimal,
    notes: str = "",
    adjustment_previous_quantity: Decimal = None,
) -> StockMovement:
    """
    Creates the StockMovement record for a reversal.
    Centralised here so all reversal strategies produce consistent records.
    """
    auto_notes = f"Reversal of {original.movement_type} #{original.pk}."
    return StockMovement.objects.create(
        movement_type=MovementType.REVERSAL,
        status=MovementStatus.CONFIRMED,
        product=original.product,
        source_branch=source_branch,
        destination_branch=destination_branch,
        quantity=quantity,
        adjustment_previous_quantity=adjustment_previous_quantity,
        reverses_movement=original,
        created_by=user,
        notes=f"{auto_notes} {notes}".strip(),
    )


def _reverse_ingreso(movement: StockMovement, user) -> StockMovement:
    """
    Ingreso added stock to destination_branch.
    Reversal removes that same quantity.
    Requires: destination_branch stock >= original quantity.
    """
    with transaction.atomic():
        stock = _lock_stock(movement.product_id, movement.destination_branch_id)

        if stock.quantity < movement.quantity:
            raise InsufficientStockError(
                f"Cannot reverse entry: insufficient stock at destination branch. "
                f"Available: {stock.quantity}, required: {movement.quantity}."
            )

        stock.quantity -= movement.quantity
        stock.save(update_fields=["quantity", "updated_at"])

        return _create_reversal_record(
            original=movement,
            user=user,
            source_branch=movement.destination_branch,
            quantity=movement.quantity,
        )


def _reverse_venta(movement: StockMovement, user) -> StockMovement:
    """
    Venta removed stock from source_branch.
    Reversal restores that quantity to the same branch.
    """
    with transaction.atomic():
        stock = _get_or_create_and_lock_stock(
            movement.product_id, movement.source_branch_id
        )
        stock.quantity += movement.quantity
        stock.save(update_fields=["quantity", "updated_at"])

        return _create_reversal_record(
            original=movement,
            user=user,
            destination_branch=movement.source_branch,
            quantity=movement.quantity,
        )


def _reverse_transferencia(movement: StockMovement, user) -> StockMovement:
    """
    Confirmed transfer moved stock source → destination.
    Reversal moves it back: destination -= qty, source += qty.

    Locks are acquired in ascending branch_id order (same as the
    original transfer service) to prevent deadlocks.
    """
    with transaction.atomic():
        source_stock, dest_stock = _lock_two_stocks(
            movement.product_id,
            movement.source_branch_id,
            movement.destination_branch_id,
        )

        if dest_stock.quantity < movement.quantity:
            raise InsufficientStockError(
                f"Cannot reverse transfer: insufficient stock at destination branch. "
                f"Available: {dest_stock.quantity}, required: {movement.quantity}."
            )

        dest_stock.quantity   -= movement.quantity
        source_stock.quantity += movement.quantity

        Stock.objects.bulk_update(
            [source_stock, dest_stock],
            ["quantity", "updated_at"],
        )

        return _create_reversal_record(
            original=movement,
            user=user,
            # Direction is inverted: goods travel back from dest to source
            source_branch=movement.destination_branch,
            destination_branch=movement.source_branch,
            quantity=movement.quantity,
        )


def _reverse_ajuste(movement: StockMovement, user) -> StockMovement:
    """
    Ajuste set stock to an absolute value.
    Reversal restores stock to adjustment_previous_quantity.

    The quantity stored in the reversal record is the delta magnitude
    so the non-negativity constraint on the movement model is respected
    even when restoring to zero.
    """
    if movement.adjustment_previous_quantity is None:
        raise InvalidMovementError(
            "Cannot reverse this adjustment: the previous quantity was not "
            "recorded at the time of creation."
        )

    restore_to = movement.adjustment_previous_quantity

    with transaction.atomic():
        stock = _get_or_create_and_lock_stock(
            movement.product_id, movement.destination_branch_id
        )
        current_quantity = stock.quantity

        stock.quantity = restore_to
        stock.save(update_fields=["quantity", "updated_at"])

        # Magnitude of the stock change — always > 0 because we guard
        # against same-quantity adjustments in the ajuste service.
        delta = abs(current_quantity - restore_to)
        # Minimum Decimal("0.001") to satisfy the model's MinValueValidator
        record_quantity = delta if delta > 0 else Decimal("0.001")

        return _create_reversal_record(
            original=movement,
            user=user,
            destination_branch=movement.destination_branch,
            quantity=record_quantity,
            adjustment_previous_quantity=current_quantity,
            notes=f"Restoring stock from {current_quantity} to {restore_to}.",
        )


def _reverse_devolucion(movement: StockMovement, user) -> StockMovement:
    """
    Devolucion added stock to destination_branch (the original sale branch).
    Reversal removes that same quantity.
    Requires: destination_branch stock >= original quantity.
    """
    with transaction.atomic():
        stock = _lock_stock(movement.product_id, movement.destination_branch_id)

        if stock.quantity < movement.quantity:
            raise InsufficientStockError(
                f"Cannot reverse return: insufficient stock at branch. "
                f"Available: {stock.quantity}, required: {movement.quantity}."
            )

        stock.quantity -= movement.quantity
        stock.save(update_fields=["quantity", "updated_at"])

        return _create_reversal_record(
            original=movement,
            user=user,
            source_branch=movement.destination_branch,
            quantity=movement.quantity,
        )


def _reverse_donacion(movement: StockMovement, user) -> StockMovement:
    """
    Donacion removed stock from source_branch.
    Reversal adds it back (stock is treated as returned from the donation).
    """
    with transaction.atomic():
        stock = _get_or_create_and_lock_stock(
            movement.product_id, movement.source_branch_id
        )
        stock.quantity += movement.quantity
        stock.save(update_fields=["quantity", "updated_at"])

        return _create_reversal_record(
            original=movement,
            user=user,
            destination_branch=movement.source_branch,
            quantity=movement.quantity,
        )


# Registered after the functions are defined so each key maps
# to an already-resolved callable.
_REVERSAL_STRATEGIES = {
    MovementType.INGRESO:       _reverse_ingreso,
    MovementType.VENTA:         _reverse_venta,
    MovementType.TRANSFERENCIA: _reverse_transferencia,
    MovementType.AJUSTE:        _reverse_ajuste,
    MovementType.DEVOLUCION:    _reverse_devolucion,
    MovementType.DONACION:      _reverse_donacion,
}
