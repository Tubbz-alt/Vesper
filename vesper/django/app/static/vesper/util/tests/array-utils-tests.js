import { ArrayUtils } from '/static/vesper/util/array-utils.js';


describe('ArrayUtils', () => {


	it('rangeArray', () => {

		const cases = [

			// one argument
			[[0], []],
			[[-1], []],
			[[1], [0]],
			[[2], [0, 1]],

			// two arguments
			[[1, 1], []],
			[[1, 2], [1]],
			[[1, 3], [1, 2]],

			// three arguments, positive increment
			[[1, 1, 1], []],
			[[1, 3, 1], [1, 2]],
			[[1, 2, .5], [1, 1.5]],
			[[1, 5, 2], [1, 3]],

			// three arguments, negative increment
			[[1, 1, -1], []],
			[[1, -1, -1], [1, 0]],
			[[1, 0, -.5], [1, .5]],
			[[1, -3, -2], [1, -1]]

		];

		for (const [args, expected] of cases) {
			const result = ArrayUtils.rangeArray(...args);
			expect(result).toEqual(expected);
		}

	});


	it('findLastLE', () => {

		const cases = [

		    // one x
		    [[0], -2, -1],
		    [[0], -.1, -1],
		    [[0], 0, 0],
		    [[0], 1, 0],

		    // two x's
		    [[0, 1], -2, -1],
		    [[0, 1], -.1, -1],
		    [[0, 1], 0, 0],
		    [[0, 1], .5, 0],
		    [[0, 1], 1, 1],
		    [[0, 1], 2, 1],

		    // several x's
		    [[0, 1, 2, 3], -2, -1],
		    [[0, 1, 2, 3], -.1, -1],
		    [[0, 1, 2, 3], 0, 0],
		    [[0, 1, 2, 3], .5, 0],
		    [[0, 1, 2, 3], 1, 1],
		    [[0, 1, 2, 3], 2.5, 2],
		    [[0, 1, 2, 3], 3, 3],
		    [[0, 1, 2, 3], 4, 3]

		];

		for (let [xs, x, expected] of cases) {
			const actual = ArrayUtils.findLastLE(xs, x);
			expect(actual).toBe(expected);
		}

	});


});
