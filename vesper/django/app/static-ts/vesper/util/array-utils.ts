/*
 * Utility functions pertaining to arrays.
 */


export namespace ArrayUtils {

	export function rangeArray(
		a: number, b: number | null = null, inc = 1
	): number[] {

		if (inc == 0) {
			throw new Error('range increment must be nonzero');
		}

		let start: number;
	    let end: number;

		if (b === null) {
			start = 0;
			end = a;
		} else {
			start = a;
			end = b;
		}

		const result: number[] = [];
		if (inc > 0) {
			for (let i = start; i < end; i += inc)
				result.push(i);
		} else {
			for (let i = start; i > end; i += inc)
				result.push(i);
		}

		return result;

	}


	export function arraysEqual(a: any[], b: any[]): boolean {

		if (a.length !== b.length)
			return false;

		else {

			const n = a.length;

			for (let i = 0; i < n; i++)
				if (a[i] !== b[i])
					return false;

			return true;

		}

	}


	/**
	 * Finds the index of the last element of array a that is less
	 * than or equal to x. The array must not be empty and its elements
	 * must be in nondecreasing order.
	 */
	export function findLastLE(a: number[], x: number): number {

		if (x < a[0])
			return -1;

		else {

			let low = 0;
			let high = a.length;
			let mid: number;

			// invariant: result is in [low, high)

			while (high != low + 1) {

				mid = Math.floor((low + high) / 2);

				if (a[mid] <= x)
					low = mid;
				else
					high = mid;

			}

			return low;

		}

	}


}
