{
  description = "Reproducible search backend evaluation: Elasticsearch vs Typesense over NixOS data";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;

        searcheval = python.pkgs.buildPythonApplication {
          pname = "searcheval";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          build-system = [ python.pkgs.hatchling ];

          # brotli is optional at the pyproject level, but the packaged app
          # bundles it so `searcheval-fetch-corpus` works out of the box.
          dependencies = with python.pkgs; [ requests brotli ];

          nativeCheckInputs = [ python.pkgs.pytestCheckHook ];

          pythonImportsCheck = [ "searcheval" ];

          meta = {
            description = "Elasticsearch vs Typesense evaluation harness over NixOS packages and options";
            mainProgram = "searcheval";
          };
        };
      in
      {
        packages = {
          default = searcheval;
          searcheval = searcheval;
        };

        apps = {
          default = {
            type = "app";
            program = "${searcheval}/bin/searcheval";
          };
          fetch-corpus = {
            type = "app";
            program = "${searcheval}/bin/searcheval-fetch-corpus";
          };
        };

        devShells.default = pkgs.mkShell {
          inputsFrom = [ searcheval ];
          packages = [
            (python.withPackages (ps: with ps; [ requests brotli pytest ]))
            pkgs.brotli
          ];
          shellHook = ''
            echo "searcheval dev shell — $(python --version)"
            echo "run tests:  pytest"
            echo "run eval:   python -m searcheval.cli --corpus corpus/full.json --queries queries/queries.json"
          '';
        };
      });
}
