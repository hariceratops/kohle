class CategoryError(Exception):
    pass


class EmptyCategoryName(CategoryError):
    def __str__(self) -> str:
        return "Category name cannot be empty"


class DuplicateCategory(CategoryError):
    def __str__(self) -> str:
        return "Category already exists"

