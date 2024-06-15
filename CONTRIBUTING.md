# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Github is used for everything

Github is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints (using `scripts/lint`).
4. Test you contribution.
5. Issue that pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Use a Consistent Coding Style

Use the configured linter to check your code, and make sure it follows the project conventions.

## Local development environment

Visual Studio Code is the recommended code editor for this project.
This project includes a [devcontainer](./.devcontainer) configuration for an easy to use and consistent development environment. With this container you will have a stand alone Home Assistant instance running and already configured with the included [`configuration.yaml`](./config/configuration.yaml) file.

### Dependency management
Dependencies are managed via [Poetry](https://python-poetry.org). This will be managed for you automatically if using the dev container. If you wish to run outside of a dev container, you will need to install your dependencies manually:

```sh
pip install poetry~=1.8
poetry install
```

### Running tests
Use `./scripts/test` to invoke the test runner.

You must be within the virtual environment where project dependencies are installed:

```sh
poetry run ./scripts/test
```

Alternatively:

```sh
poetry shell
# you now have a shell within the virtual env
./scripts/test
```

### Updating snapshots
If you've made a change to code that impacts a snapshot, your test will fail and the snapshot needs to be updated. To update snapshots run /bin/bash ./scripts/update_snapshots

Or in vscode you can run one of the two update snapshot tasks by opening the command pallete with cmd + p (or ctrl + p), and type `task Update` to see the tasks related to updating snapshots.

### Linting
In the devcontainer, linting and formatting runs on save and linting errors are showed as PROBLEMS in vscode.

To invoke a full lint/format, in vscode open the command pallete with cmd + p (or ctrl + p), and type `task Lint`.

Alternatively use `./scripts/lint` to invoke the project linter. You must be within the virtual environment where project dependencies are installed:

```sh
poetry run ./scripts/lint
```

Alternatively:

```sh
poetry shell
# you now have a shell within the virtual env
./scripts/lint
```

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
