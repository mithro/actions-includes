# actions-includes

Allows including an action inside another action (by preprocessing the Yaml file).

Instead of using `uses` or `run` in your action step, use the keyword `includes`.

Once you are using the `includes` argument, the workflows can be expanded using
the tool like follows;
```
# python -m actions_include <input-workflow-with-includes> <output-workflow-flattened>
python -m actions_includes ./.github/workflows-src/workflow-a.yml ./.github/workflows/workflow-a.yml
```


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
 - `./{path}` - Local action under local `{path}, IE `./.github/actions/my-action`.

As it only makes sense to reference composite actions, the `docker://` form isn't supported.

As you frequently want to include local actions, `actions-includes` extends the
`{action-name}` syntax to also support;

 - `/{name}` - Local action under `./.github/actions/{name}`.

This is how composite actions should have worked.


