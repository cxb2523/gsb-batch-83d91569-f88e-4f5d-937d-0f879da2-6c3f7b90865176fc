import marimo

__generated_with = "0.23.13"
app = marimo.App()


@app.cell
def _():
    value = 2 + 2
    return (value,)


@app.cell
def _(value):
    value
    return


if __name__ == "__main__":
    app.run()
