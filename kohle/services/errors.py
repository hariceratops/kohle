class CategoryError(Exception):
    pass

class EmptyCategoryError(CategoryError):
    pass

class DuplicateCategoryError(CategoryError):
    pass

class DatabaseError(CategoryError):
    pass

