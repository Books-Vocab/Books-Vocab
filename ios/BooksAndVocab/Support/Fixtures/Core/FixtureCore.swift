import Foundation

enum FixtureSurface: String, Hashable {
    case preview
    case catalog
    case snapshot
    case marketing
}

struct FixtureKey: RawRepresentable, Hashable, ExpressibleByStringLiteral {
    let rawValue: String

    init(rawValue: String) {
        self.rawValue = rawValue
    }

    init(_ rawValue: String) {
        self.rawValue = rawValue
    }

    init(stringLiteral value: StringLiteralType) {
        self.init(value)
    }
}

struct FixtureRecipe<Seed> {
    let key: FixtureKey
    let surfaces: Set<FixtureSurface>
    let tags: Set<String>
    let build: () -> Seed

    init(
        key: FixtureKey,
        surfaces: Set<FixtureSurface>,
        tags: Set<String> = [],
        build: @escaping () -> Seed
    ) {
        self.key = key
        self.surfaces = surfaces
        self.tags = tags
        self.build = build
    }
}

struct FixtureRegistry<Seed> {
    private let orderedRecipes: [FixtureRecipe<Seed>]
    private let indexByKey: [FixtureKey: Int]

    init(_ recipes: [FixtureRecipe<Seed>]) {
        var seen = Set<FixtureKey>()
        for recipe in recipes {
            precondition(seen.insert(recipe.key).inserted, "Duplicate fixture key: \(recipe.key.rawValue)")
        }

        orderedRecipes = recipes
        indexByKey = Dictionary(uniqueKeysWithValues: recipes.enumerated().map { ($0.element.key, $0.offset) })
    }

    func recipe(for key: FixtureKey) -> FixtureRecipe<Seed> {
        guard let index = indexByKey[key] else {
            fatalError("Unknown fixture key: \(key.rawValue)")
        }
        return orderedRecipes[index]
    }

    func recipes(for surface: FixtureSurface) -> [FixtureRecipe<Seed>] {
        orderedRecipes.filter { $0.surfaces.contains(surface) }
    }
}
