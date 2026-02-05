from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from kohle.core.result import Result
from kohle.services.errors import DatabaseError, DuplicateCategoryError


class UnitOfWork:
    """Unit of Work handles session lifecycle and DB errors."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def run(self, func):
        session = self._session_factory()
        try:
            value = func(session)

            # flush to catch integrity errors early
            session.flush()
            session.commit()

            return Result.ok(value)

        except IntegrityError:
            session.rollback()
            return Result.err(DuplicateCategoryError())

        except SQLAlchemyError as e:
            session.rollback()
            return Result.err(DatabaseError(str(e)))

        finally:
            session.close()

