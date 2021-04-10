# actions-includes

[![License](https://img.shields.io/github/license/mithro/actions-includes.svg)](https://github.com/mithro/actions-includes/blob/master/LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/mithro/actions-includes)](https://github.com/mithro/actions-includes/issues)
![PyPI](https://img.shields.io/pypi/v/actions-includes)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/actions-includes)
![PyPI - Downloads](https://img.shields.io/pypi/dm/actions-includes)


Allows including an action inside another action (by preprocessing the YAML file).

Instead of using `uses` or `run` in your action step, use the keyword `includes`.

Once you are using the `includes` argument, the workflows can be expanded using this tool as follows:
```sh
# python -m actions_include <input-workflow-with-includes> <output-workflow-flattened>

python -m actions_includes ./.github/workflows-src/workflow-a.yml ./.github/workflows/workflow-a.yml
```

## `includes:` step

```yaml

steps:
- name: Other step
  run: |
    command

- includes: {action-name}
  with:
    {inputs}

- name: Other step
  run: |
    command
```

The `{action-name}` follows the same syntax as the standard GitHub action
[`uses`](https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions#jobsjob_idstepsuses)
and the action referenced should look exactly like a
[GitHub "composite action"](https://docs.github.com/en/actions/creating-actions/creating-a-composite-run-steps-action)
**except** `runs.using` should be `includes`.

For example;
 - `{owner}/{repo}@{ref}` - Public action in `github.com/{owner}/{repo}`
 - `{owner}/{repo}/{path}@{ref}` - Public action under `{path}` in
   `github.com/{owner}/{repo}`.
 - `./{path}` - Local action under local `{path}`, IE `./.github/actions/{action-name}`.

As it only makes sense to reference composite actions, the `docker://` form isn't supported.

As you frequently want to include local actions, `actions-includes` extends the 
`{action-name}` syntax to also support:

 - `/{name}` - Local action under `./.github/actions/includes/{name}`.

This is how composite actions should have worked.

## `includes-script:`
You can include a script (e.g., a Python or shell script) in your workflow.yml file using the `includes-script` step.

Example script file: `script.py`
> ```python
> print('Hello world')
> ```

To include the script, reference it in an `includes-script` action in your `workflow.yml`, like so:
> ```yaml
> steps:
> - name: Other step
>   run: |
>     command
>
> - name: Hello
>   includes-script: script.py
>
> - name: Other step
>   run: |
>     command
> ```

When the workflow.yml is processed by running
```python -m actions_includes.py workflow.in.yml workflow.out.yml```,
the resultant `workflow.out.yml` looks like this:
> ```yaml
> steps:
> - name: Other step
>   run: |
>     command
> 
> - name: Hello
>   shell: python
>   run: |
>     print('Hello world')
> 
> - name: Other step
>   run: |
>     command
> ```
The `shell` parameter is deduced from the file extension, 
but it is possible to use a custom shell by setting the 
`shell` parameter manually.

## Using a pre-commit hook
When you use actions-includes, it may be useful to add a pre-commit hook 
(see https://git-scm.com/docs/githooks) to your project so that your workflow 
files are always pre-processed before they reach GitHub. 

### With a git hooks package
There are multiple packages (notably `pre-commit`; 
see https://pre-commit.com/) that support adding pre-commit hooks.

In the case of using the `pre-commit` package, you can add an entry 
such as the following to your `pre-commit-config.yaml` file:
> ```
> - repo: local
>   hooks:
>   - id: preprocess-workflows
>     name: Preprocess workflow.yml
>     entry: python -m actions_includes.py workflow.in.yml workflow.out.yml
>     language: system
>     always-run: true
> ```

### Without a git hooks package
Alternatively, to add a pre-commit hook without installing another 
package, you can simply create or modify `.git/hooks/pre-commit`
(relative to your project root). A sample file typically 
lives at `.git/hooks/pre-commit.sample`.

The pre-commit hook should run the commands that are necessary to 
pre-process your workflows. So, your `.git/hooks/pre-commit` file 
might look something like this:
> ```sh
> #!/bin/bash
>
> python -m actions_includes.py workflow.in.yml workflow.out.yml || {
>     echo "Failed to preprocess workflow file."""
> }
> ```

To track this script in source code management, you'll have to
put it in a non-ignored file in your project that is then copied to 
`.git/hooks/pre-commit` as part of your project setup. See
https://github.com/ModularHistory/modularhistory for an example
of a project that does this with a setup script (`setup.sh`).
