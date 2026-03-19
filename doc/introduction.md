# Introduction to CTD

CTD files describe the expected composition of test data files using a small grammar.
One line of input consisting of two small integers separated by space is specified like this:

<table>
<tr><th>CTD<th>Accept<th>Reject<th>Reject<th>Reject<th>Reject<th>Reject</tr>
<tr><td>

```
INT(1, 10)
SPACE
INT(1, 10)
NEWLINE
```

<td>

`4 6`

<td>

`4 6 5`

<td>

`4`

<td>

`11 6`
<td>


```text
4
6
```

<td>`four`
</table>

CTD-files are whitespace-agnostic, so the above is the same as

```
INT(1, 10) SPACE INT(1, 10) NEWLINE
```

but different from requiring exactly two spaces between the integers:

```
INT(1, 10) SPACE SPACE INT(1, 10) NEWLINE
```

`INT(min, max, name)` takes an optional third argument that assigns the matched integer to a variable name.
Variable names consist of lower case alphanumeric characters `a0`, or integer-indexed array entries like `a[2]`.
You can also use variable and expressions for the first two arguments of `INT`:

```
INT(1, 9, a) SPACE INT(a + 1, 10) NEWLINE # specify 1 <= a < b <= 10
```

`#` starts a comment.

Keywords like `INT(min, max)` and `SPACE` match characters in the input.
Others express constraints. To specify that the two integers must be different, use `ASSERT`:

<table>
<tr><th>CTD<th>Accept<th>Reject</tr>
<tr><td>
```
INT(1, 10, x) SPACE INT(1, 10, y) NEWLINE
ASSERT (x != y)
```
<td>`4 6`<td>`4 4`</table>

You can write `ASSERT (x < y)` or even `ASSERT (x < y || x > y && x == 3)`.


## Numbers

Number representations are picky about redundant initial `0`s and signs.

| CTD | Accept | Accept | Reject | Reject | Reject |
| --- | --- | ---| ---|--- | ---|
| `INT(-10,10)` | `10`|  `-10`| `010`| `10.0`| `+10`|


| CTD | Acc | Acc | Acc | Acc | Acc | Acc | Rej | Rej | Rej |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |  --- | --- |
| `FLOAT(5.5, 10)`  | `10` | `10.0` |  `5.50` |`1e1`| `1e+1`| `1E1`| `10.`| `5.4`| `+1e1`

Use `FLOAT(min, max, FIXED)` to insist on fixed-point notation (i.e., disallowing scientific notation like `1e1`).

`FLOATP(min, max, mindecimals, maxdecimals)` specifies the number of decimals.

## Strings

An exact string is matched as

```
STRING("hello") NEWLINE
```
More generally, strings are matched with regular expressions:

```
REGEX("yes|no") NEWLINE
```

Matches can be assigned to variables, which can occur in assertions; `STRLEN` gives the length of a named string.

<table>
<tr><th>CTD<th>Accept<th>Reject<th>Reject
<tr>
<td>
```
INT(1, 200000, n) NEWLINE
REGEX("[()\[\]]+", brackets) NEWLINE
ASSERT(STRLEN(brackets) == n)
```
<td>
```text
5
)([](
```
<td>
```
5
()()
```
<td>
```
4
(){}
```
</table>


Strings can be compared lexicographically:


<table><tr>
<th>CTD
<th>Accept
<th>Accept
<th>Reject
<tr><td>
```
REGEX("[a-z]+", first) SPACE REGEX("[a-z]+", second) NEWLINE
ASSERT (first < second)
```
<td> `a aa`
<td> `11 9`
<td> `foo foo`
</table>

## Selection

Check either an integer or the word `impossible`:

<table>
<tr>
<th>CTD<th>Accept<th>Accept<th>Reject
<tr>
<td>
```
IF (MATCH("i"))
    STRING("impossible")
ELSE
    INT(1,100)
END
NEWLINE
```
<td>`impossible`
<td>`42`
<td>`impossible 42`
</table>

The else-branch is optional, we could also do

```
IF (MATCH("i")) # conditions in brackets
    STRING("impossible")
END
IF (MATCH("123456789")) # match any of the characters
    INT(1,100)
END
NEWLINE
```

## Iteration

The input consists of

* one line with an integer $n$ ($1 \leq n \leq 100$), the number of lines
* $n$ lines, each consisting of two different integers $x$, $y$

<table>
<tr><th>CTD<th>Accept<th>Reject</tr>
<tr><td>
```
INT(1, 100, n) NEWLINE
REP(n)
    INT(1, 1000, x) SPACE INT(1, 1000, y) NEWLINE
    ASSERT (x != y)
END
```
<td>
```text
3
42 43
99 1
42 43
```
<td>
```text
3
12 13
14 14
15 16
```
</tr>
</table>

An optional second argument to REP defines a separation character between matches.
To specify

* one line with an integer _n_ ($1 \leq n \leq 100$), the number of measurements
* one line with $n$ measurements, each between 10 and 20 inclusive:

<table>
<tr><th>CTD<th>Accept<th>Reject</tr>
<td>
```
INT(1, 100, n) NEWLINE
REP(n, SPACE)
    INT(10, 20)
END
NEWLINE
```
<td>
```text
3
10 14 12
```
<td>
```text
3
10 14 12 11
```
</table>

## Arrays

Variables can form arrays, and arrays allow membership and uniqueness tests.

Here we check that the first number appears among following five numbers.
The `REPI` ... `END` part matches a line 5 integers and assigns `p[0]`, ..., `p[4]` to  them.
Together these variables form an array variable called `p`.
`INARRAY` then performs the membeship test.

<table>
<tr><th>CTD<th>Accept<th>Reject</tr>
<tr><td>
```
INT(1,10, a) SPACE
REPI(i, 5, SPACE) INT(1, 10, bs[i]) END NEWLINE
ASSERT(INARRAY(a, bs))
```
<td>
`1 5 4 3 2 1`
<td> `1 6 5 4 3 2`
</tr>
</table>

Use `UNIQUE` to ensure that all elements in an array are different. Here we check for two permutations.
<table>
<tr><th>CTD<th>Accept<th>Reject<th>Reject</tr>
<tr><td>
```
REPI(i, 5, SPACE)
    INT(1, 5, p[i])
END SPACE
REPI(i, 5)
    REGEX("A|E|I|O|U", v[i])
END NEWLINE
ASSERT(UNIQUE(p))
ASSERT(UNIQUE(v))
```
<td>
`1 4 5 2 3 AOIUE`
<td> `1 4 4 2 3 AOIUE`
<td> `1 4 5 2 3 AOIIE`
</tr>
</table>

The `UNIQUE` constraint checks that the entries of its argument are unique.

`UNIQUE` can take several arrays. With $k$ arguments, `UNIQUE`$(a_1, a_2,\ldots, a_k)$ means that each $a_i$ must be an array variable of the same length $n$, and the $k$-tuples $(a_1[j], \ldots, a_k[j])$ for $0\leq j< n$ must be unique.
Use this to specify lists of unique coordinates or graph edges.

<table>
<tr><th>CTD<th>Accept<th>Reject</tr>
<tr><td>
```
REPI(i, 3)
    INT(1, 100, u[i])
    SPACE
    INT(1, 100, v[i])
    NEWLINE
END
ASSERT(UNIQUE(u, v))
```
<td>
```
1 2
3 3
2 1
```
<td>
```
1 2
1 3
1 2
```
</tr>
</table>
